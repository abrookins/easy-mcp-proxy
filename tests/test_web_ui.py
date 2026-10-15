"""Tests for the web UI routes and helpers."""

import base64
import json
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_proxy import web_ui
from mcp_proxy.api_keys import ApiKeyStore
from mcp_proxy.auth import CompositeAuthProvider, RestrictedAuthProvider
from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy
from mcp_proxy.web_ui import (
    CSRF_HEADER,
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    Identity,
    _create_signed_cookie,
    _decode_jwt_claims,
    _exchange_code_for_claims,
    _get_oauth_credentials,
    _get_oidc_provider,
    _get_restricted_provider,
    _get_session_secret,
    _safe_return_url,
    _sign_session_data,
    _verify_session_data,
    _verify_signed_cookie,
    build_error_html,
    create_session_cookie,
    create_web_ui_routes,
    get_config_path,
    get_overrides_path,
    is_browser_request,
    load_merged_config,
    load_overrides,
    load_raw_config,
    save_config,
    save_overrides,
    verify_session_cookie,
)

ADMIN = "admin@example.com"
USER = "user@example.com"
JSON = {"Accept": "application/json"}
HTML = {"Accept": "text/html"}


@pytest.fixture(autouse=True)
def session_secret(monkeypatch):
    monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID", "client-123")


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "mcp_servers": {
                    "fetch": {"command": "uvx", "args": ["mcp-server-fetch", "--x"]}
                },
                "tool_views": {"default": {"description": "Default"}},
                "admins": [ADMIN],
            }
        )
    )
    return path


def _oidc(userinfo="https://idp.example.com/userinfo"):
    return SimpleNamespace(
        oidc_config=SimpleNamespace(
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/oauth/token",
            userinfo_endpoint=userinfo,
        )
    )


def _auth_provider(tokens=None):
    """Fake auth provider: maps bearer tokens to claims."""
    tokens = tokens or {}

    async def verify_token(token):
        if token not in tokens:
            return None
        return SimpleNamespace(claims=tokens[token])

    provider = _oidc()
    provider.verify_token = verify_token
    return provider


def _client(config_path, auth_provider=None, proxy=None, api_key_store=None):
    app = Starlette(
        routes=create_web_ui_routes(
            path_prefix="/config",
            auth_provider=auth_provider,
            proxy=proxy,
            config_path=config_path,
            api_key_store=api_key_store,
        )
    )
    return TestClient(app, follow_redirects=False)


def _bearer(token):
    return {**JSON, "Authorization": f"Bearer {token}"}


def _jwt(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"header.{payload.decode()}.signature"


class TestConfigFiles:
    def test_get_config_path(self, monkeypatch):
        monkeypatch.delenv("MCP_PROXY_CONFIG", raising=False)
        assert get_config_path() == Path("config.yaml")
        monkeypatch.setenv("MCP_PROXY_CONFIG", "/etc/proxy.yaml")
        assert get_config_path() == Path("/etc/proxy.yaml")

    def test_overrides_path(self):
        assert get_overrides_path(Path("/a/c.yaml")) == Path("/a/c.overrides.json")

    def test_load_raw_config(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        assert load_raw_config(missing) == {"mcp_servers": {}, "tool_views": {}}
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        assert load_raw_config(empty) == {}

    def test_overrides_round_trip(self, config_path):
        assert load_overrides(config_path) == {}
        save_overrides(config_path, {"admins": ["x@example.com"]})
        assert load_overrides(config_path) == {"admins": ["x@example.com"]}

    def test_save_config_persists_deletions_and_keeps_yaml(self, config_path):
        original_yaml = config_path.read_text()
        config = load_merged_config(config_path)
        del config["mcp_servers"]["fetch"]
        config["mcp_servers"]["git"] = {"command": "uvx", "args": ["mcp-git"]}

        save_config(config_path, config)

        assert config_path.read_text() == original_yaml
        assert load_merged_config(config_path) == config

    def test_save_config_validates(self, config_path):
        with pytest.raises(ValidationError):
            save_config(config_path, {"unknown_key": True})
        assert load_overrides(config_path) == {}


class TestSignedCookies:
    def test_session_secret(self, monkeypatch):
        assert _get_session_secret() == "test-secret"
        monkeypatch.delenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET")
        assert _get_session_secret() == _get_session_secret()
        assert _get_session_secret() == web_ui._FALLBACK_SESSION_SECRET

    def test_round_trip(self):
        cookie = create_session_cookie("sub-1", USER)
        session = verify_session_cookie(cookie)
        assert session["user_id"] == "sub-1"
        assert session["email"] == USER

    def test_rejects_tampering(self):
        assert _verify_session_data("no-signature") is None
        signed = _sign_session_data("data")
        assert _verify_session_data(signed) == "data"
        assert _verify_session_data(signed[:-1] + "0") is None
        assert verify_session_cookie("garbage") is None

    def test_rejects_bad_payloads(self):
        def signed(text):
            return _sign_session_data(base64.urlsafe_b64encode(text.encode()).decode())

        assert _verify_signed_cookie(_sign_session_data("!!")) is None
        assert _verify_signed_cookie(signed("not json")) is None
        assert _verify_signed_cookie(signed("[1]")) is None
        expired = signed(json.dumps({"expires": time.time() - 1}))
        assert _verify_signed_cookie(expired) is None
        assert _verify_signed_cookie(_create_signed_cookie({"a": 1}, 60))["a"] == 1


class TestHelpers:
    def test_error_html_is_escaped(self):
        page = build_error_html("<b>", "<script>")
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_is_browser_request(self):
        assert is_browser_request(SimpleNamespace(headers=HTML))
        assert not is_browser_request(SimpleNamespace(headers=JSON))

    def test_safe_return_url(self):
        assert _safe_return_url("/config#/views", "/config") == "/config#/views"
        for bad in ["https://evil.example", "//evil.example", "/\\evil", "x"]:
            assert _safe_return_url(bad, "/config") == "/config"

    def test_get_oidc_provider(self):
        oidc = _oidc()
        restricted = RestrictedAuthProvider(oidc, allowed_emails={USER})
        composite = CompositeAuthProvider(
            static_provider=SimpleNamespace(), oidc_provider=restricted
        )
        assert _get_oidc_provider(None) is None
        assert _get_oidc_provider(oidc) is oidc
        assert _get_oidc_provider(composite) is oidc
        assert _get_oidc_provider(CompositeAuthProvider()) is None

    def test_get_restricted_provider(self):
        oidc = _oidc()
        restricted = RestrictedAuthProvider(oidc, allowed_emails={USER})
        assert _get_restricted_provider(None) is None
        assert _get_restricted_provider(restricted) is restricted
        assert (
            _get_restricted_provider(CompositeAuthProvider(oidc_provider=restricted))
            is restricted
        )
        assert _get_restricted_provider(CompositeAuthProvider(oidc_provider=oidc)) is (
            None
        )

    def test_oauth_credentials(self):
        assert _get_oauth_credentials() == ("client-123", "test-secret")

    def test_decode_jwt_claims(self):
        assert _decode_jwt_claims(_jwt({"email": USER})) == {"email": USER}
        assert _decode_jwt_claims("") == {}
        assert _decode_jwt_claims("a.!!!.c") == {}
        assert _decode_jwt_claims(_jwt([1])) == {}

    def test_identity_is_admin(self):
        assert Identity(email=None, auth_enabled=False).is_admin([])
        assert not Identity(email=None).is_admin([ADMIN])
        assert Identity(email="Admin@Example.com").is_admin([ADMIN])
        assert not Identity(email=USER).is_admin([ADMIN])


def _mock_httpx(token_response, userinfo_response=None, error=None):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=token_response, side_effect=error)
    client.get = AsyncMock(return_value=userinfo_response)
    return patch("httpx.AsyncClient", return_value=client), client


def _response(status, payload):
    return SimpleNamespace(status_code=status, json=lambda: payload)


class TestExchangeCode:
    async def test_merges_id_token_and_userinfo(self):
        tokens = {"access_token": "at", "id_token": _jwt({"sub": "s1"})}
        patcher, client = _mock_httpx(
            _response(200, tokens), _response(200, {"email": USER})
        )
        with patcher:
            claims = await _exchange_code_for_claims(_oidc().oidc_config, "c", "/cb")
        assert claims == {"sub": "s1", "email": USER}
        assert client.post.call_args.kwargs["data"]["client_id"] == "client-123"
        assert client.get.call_args.kwargs["headers"] == {"Authorization": "Bearer at"}

    async def test_without_userinfo_endpoint_or_failed_userinfo(self):
        tokens = {"access_token": "at", "id_token": _jwt({"email": USER})}
        patcher, client = _mock_httpx(_response(200, tokens))
        with patcher:
            claims = await _exchange_code_for_claims(
                _oidc(userinfo=None).oidc_config, "c", "/cb"
            )
        assert claims == {"email": USER}
        client.get.assert_not_called()

        patcher, _ = _mock_httpx(_response(200, tokens), _response(500, {}))
        with patcher:
            claims = await _exchange_code_for_claims(_oidc().oidc_config, "c", "/cb")
        assert claims == {"email": USER}

    async def test_failures_return_none(self):
        patcher, _ = _mock_httpx(_response(400, {}))
        with patcher:
            assert await _exchange_code_for_claims(_oidc().oidc_config, "c", "/cb") is (
                None
            )
        patcher, _ = _mock_httpx(None, error=httpx.ConnectError("down"))
        with patcher:
            assert await _exchange_code_for_claims(_oidc().oidc_config, "c", "/cb") is (
                None
            )


class TestAuthentication:
    def test_auth_disabled_everyone_is_admin(self, config_path):
        client = _client(config_path)
        assert client.get("/config", headers=HTML).status_code == 200
        me = client.get("/config/api/me").json()
        assert me == {
            "email": None,
            "is_admin": True,
            "auth_enabled": False,
            "api_keys_enabled": False,
        }
        assert client.get("/config/api").status_code == 200

    def test_unauthenticated_browser_redirects_api_gets_401(self, config_path):
        client = _client(config_path, _auth_provider())
        browser = client.get("/config", headers=HTML)
        assert browser.status_code == 302
        assert browser.headers["location"] == "/config/login?return_url=/config"
        api = client.get("/config/api/me", headers=JSON)
        assert api.status_code == 401
        assert api.headers["www-authenticate"] == "Bearer"
        empty = client.get("/config/api/me", headers={"Authorization": "Bearer "})
        assert empty.status_code == 401
        bad = client.get("/config/api/me", headers=_bearer("nope"))
        assert bad.status_code == 401

    def test_bearer_identity(self, config_path):
        client = _client(
            config_path,
            _auth_provider({"admin": {"email": ADMIN}, "static": {"email": 5}}),
        )
        assert client.get("/config/api/me", headers=_bearer("admin")).json()["is_admin"]
        static = client.get("/config/api/me", headers=_bearer("static")).json()
        assert static["email"] is None
        assert static["is_admin"] is False

    def test_session_identity_and_invalid_cookie(self, config_path):
        client = _client(config_path, _auth_provider())
        client.cookies.set(SESSION_COOKIE_NAME, "forged")
        assert client.get("/config/api/me").status_code == 401
        client.cookies.set(SESSION_COOKIE_NAME, create_session_cookie("s", USER))
        me = client.get("/config/api/me").json()
        assert me["email"] == USER
        assert me["is_admin"] is False

    def test_session_mutations_require_csrf_header(self, config_path):
        client = _client(config_path, _auth_provider())
        client.cookies.set(SESSION_COOKIE_NAME, create_session_cookie("s", ADMIN))
        config = client.get("/config/api").json()
        blocked = client.put("/config/api", json=config)
        assert blocked.status_code == 403
        allowed = client.put("/config/api", json=config, headers={CSRF_HEADER: "1"})
        assert allowed.status_code == 200

    def test_non_admins_cannot_read_or_change_config(self, config_path):
        client = _client(config_path, _auth_provider({"user": {"email": USER}}))
        for method, path in [
            ("GET", "/config/api"),
            ("PUT", "/config/api"),
            ("GET", "/config/api/yaml"),
            ("PUT", "/config/api/yaml"),
            ("POST", "/config/restart"),
        ]:
            response = client.request(method, path, headers=_bearer("user"))
            assert response.status_code == 403, path
            assert response.json()["error"] == "forbidden"


class TestStaticAndIndex:
    def test_index_and_assets(self, config_path):
        client = _client(config_path)
        page = client.get("/config").text
        assert 'data-prefix="/config"' in page
        assert '<script src="/config/static/app.js">' in page
        js = client.get("/config/static/app.js")
        assert js.headers["content-type"].startswith("text/javascript")
        assert "X-MCP-Proxy-UI" in js.text
        css = client.get("/config/static/app.css")
        assert css.headers["content-type"].startswith("text/css")
        assert client.get("/config/static/secret.py").status_code == 404


class TestConfigApi:
    def test_get_and_put_json(self, config_path):
        client = _client(config_path)
        config = client.get("/config/api").json()
        assert config["mcp_servers"]["fetch"]["args"] == ["mcp-server-fetch", "--x"]
        config["tool_views"]["docs"] = {"exposure_mode": "search"}
        del config["tool_views"]["default"]
        assert client.put("/config/api", json=config).json() == {"status": "saved"}
        assert client.get("/config/api").json() == config

    def test_put_json_errors(self, config_path):
        client = _client(config_path)
        not_object = client.put("/config/api", json=[1])
        assert not_object.status_code == 400
        assert not_object.json()["details"] == ["Configuration must be an object"]
        bad_json = client.put("/config/api", content=b"{", headers=JSON)
        assert bad_json.status_code == 400
        invalid = client.put("/config/api", json={"mcp_servers": {"a": {"args": 1}}})
        assert invalid.status_code == 400
        assert invalid.json()["details"][0].startswith("mcp_servers.a.args")

    def test_yaml_round_trip_and_errors(self, config_path):
        client = _client(config_path)
        text = client.get("/config/api/yaml").text
        assert "mcp-server-fetch" in text
        updated = text.replace("Default", "Updated")
        assert client.put("/config/api/yaml", content=updated).status_code == 200
        assert (
            client.get("/config/api").json()["tool_views"]["default"]["description"]
            == "Updated"
        )
        assert client.put("/config/api/yaml", content="- a").status_code == 400
        assert client.put("/config/api/yaml", content="a: [").status_code == 400

    def test_upstream_tools(self, config_path):
        assert _client(config_path).get("/config/api/upstream-tools").json() == {}
        proxy = MCPProxy(ProxyConfig())
        tool = SimpleNamespace(name="fetch", description=None)
        proxy._upstream_tools["fetch"] = [tool]
        response = _client(config_path, proxy=proxy).get("/config/api/upstream-tools")
        assert response.json() == {"fetch": [{"name": "fetch", "description": ""}]}


class TestApiKeys:
    @pytest.fixture
    def store(self, tmp_path):
        return ApiKeyStore(tmp_path / "keys.json")

    def test_users_manage_only_their_own_keys(self, config_path, store):
        auth = _auth_provider({"u": {"email": USER}, "a": {"email": ADMIN}})
        client = _client(config_path, auth, api_key_store=store)
        assert client.get("/config/api/me", headers=_bearer("u")).json()[
            "api_keys_enabled"
        ]

        created = client.post(
            "/config/api/keys", json={"name": " laptop "}, headers=_bearer("u")
        )
        assert created.status_code == 201
        key = created.json()
        assert key["name"] == "laptop"
        assert key["owner"] == USER
        assert key["key"].startswith(key["prefix"])

        mine = client.get("/config/api/keys", headers=_bearer("u")).json()["keys"]
        assert [k["id"] for k in mine] == [key["id"]]
        assert "hash" not in mine[0] and "key" not in mine[0]
        assert client.get("/config/api/keys", headers=_bearer("a")).json() == {
            "keys": []
        }

        other = client.delete(f"/config/api/keys/{key['id']}", headers=_bearer("a"))
        assert other.status_code == 404
        revoked = client.delete(f"/config/api/keys/{key['id']}", headers=_bearer("u"))
        assert revoked.json() == {"status": "revoked"}
        assert store.list_for(USER) == []

    def test_create_requires_name(self, config_path, store):
        client = _client(
            config_path,
            api_key_store=store,
            auth_provider=_auth_provider({"u": {"email": USER}}),
        )
        for body in [{"name": "  "}, {"name": 1}, [1]]:
            response = client.post("/config/api/keys", json=body, headers=_bearer("u"))
            assert response.status_code == 400
        bad_json = client.post("/config/api/keys", content=b"{", headers=_bearer("u"))
        assert bad_json.status_code == 400

    def test_unavailable_without_store_or_email(self, config_path, store):
        no_store = _client(config_path)
        no_email = _client(config_path, api_key_store=store)
        for client in [no_store, no_email]:
            assert client.get("/config/api/keys").status_code == 400
            assert client.post("/config/api/keys", json={"name": "x"}).status_code == (
                400
            )
            assert client.delete("/config/api/keys/abc").status_code == 400


class TestRestart:
    def test_restart_signals_process(self, config_path):
        with patch("mcp_proxy.web_ui.os.kill") as kill:
            response = _client(config_path).post("/config/restart")
        assert response.json() == {"status": "restart_initiated"}
        kill.assert_called_once()
        assert (config_path.parent / ".mcp-proxy-restart").exists()

    def test_restart_tolerates_marker_failure_and_reports_kill_failure(self, tmp_path):
        missing_dir_config = tmp_path / "missing" / "config.yaml"
        with patch("mcp_proxy.web_ui.os.kill", side_effect=OSError("denied")):
            response = _client(missing_dir_config).post("/config/restart")
        assert response.status_code == 500
        assert response.json() == {"error": "denied"}


class TestLogin:
    def test_login_requires_oidc(self, config_path):
        response = _client(config_path, SimpleNamespace()).get("/config/login")
        assert response.status_code == 500
        assert "Sign-in Not Configured" in response.text

    def test_login_redirects_to_provider_with_state(self, config_path):
        client = _client(config_path, _auth_provider())
        response = client.get("/config/login?return_url=https://evil.example")
        location = urllib.parse.urlparse(response.headers["location"])
        params = urllib.parse.parse_qs(location.query)
        assert location.netloc == "idp.example.com"
        assert params["client_id"] == ["client-123"]
        assert params["scope"] == ["openid email profile"]
        assert params["redirect_uri"] == ["http://testserver/config/login/callback"]
        saved = _verify_signed_cookie(client.cookies[STATE_COOKIE_NAME])
        assert saved["state"] == params["state"][0]
        assert saved["return_url"] == "/config"

    def _callback(self, client, state="s1"):
        client.cookies.set(
            STATE_COOKIE_NAME,
            _create_signed_cookie({"state": "s1", "return_url": "/config#/keys"}, 60),
        )
        return client.get(f"/config/login/callback?code=abc&state={state}")

    def test_callback_errors(self, config_path):
        client = _client(config_path, _auth_provider())
        missing_code = client.get("/config/login/callback?error=denied")
        assert missing_code.status_code == 400
        assert "denied" in missing_code.text
        assert self._callback(client, state="other").status_code == 400

        no_oidc = _client(config_path, SimpleNamespace())
        assert self._callback(no_oidc).status_code == 500

        with patch(
            "mcp_proxy.web_ui._exchange_code_for_claims",
            AsyncMock(return_value=None),
        ):
            failed = self._callback(client)
        assert "Token Exchange Failed" in failed.text

    def test_callback_enforces_allowed_emails(self, config_path):
        restricted = RestrictedAuthProvider(_oidc(), allowed_emails={ADMIN})
        client = _client(config_path, restricted)
        with patch(
            "mcp_proxy.web_ui._exchange_code_for_claims",
            AsyncMock(return_value={"email": USER, "email_verified": True}),
        ):
            response = self._callback(client)
        assert response.status_code == 403

    def test_callback_sets_session_with_email(self, config_path):
        client = _client(config_path, _auth_provider())
        claims = {"sub": "auth0|1", "email": ADMIN}
        with patch(
            "mcp_proxy.web_ui._exchange_code_for_claims",
            AsyncMock(return_value=claims),
        ):
            response = self._callback(client)
        assert response.status_code == 302
        assert response.headers["location"] == "/config#/keys"
        session = verify_session_cookie(client.cookies[SESSION_COOKIE_NAME])
        assert session["user_id"] == "auth0|1"
        assert session["email"] == ADMIN
        assert client.get("/config/api/me").json()["is_admin"] is True

    def test_callback_without_email(self, config_path):
        client = _client(config_path, _auth_provider())
        with patch(
            "mcp_proxy.web_ui._exchange_code_for_claims",
            AsyncMock(return_value={"email": ["x"]}),
        ):
            self._callback(client)
        session = verify_session_cookie(client.cookies[SESSION_COOKIE_NAME])
        assert session["email"] is None
        assert session["user_id"] == "user"

    def test_logout(self, config_path):
        client = _client(config_path, _auth_provider())
        client.cookies.set(SESSION_COOKIE_NAME, create_session_cookie("s", USER))
        response = client.get("/config/logout")
        assert response.headers["location"] == "/config/signed-out"
        assert f'{SESSION_COOKIE_NAME}=""' in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert "Sign in again" in client.get("/config/signed-out").text
