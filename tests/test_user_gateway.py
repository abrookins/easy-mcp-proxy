"""HTTP and MCP discovery use the verified user, independently of admission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from mcp_proxy.identity import AccessDenied, Identity, principal_context
from mcp_proxy.managed_config import ConfigService
from mcp_proxy.user_gateway import UserGateway, UserProvider, verified_identity
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import Conflict, UserStore


class FakeOAuth(StaticTokenVerifier):
    def __init__(self):
        super().__init__(
            tokens={
                subject: {
                    "client_id": "upstream-shared",
                    "scopes": [],
                    "iss": "issuer",
                    "sub": subject,
                }
                for subject in ("alice", "bob", "accidentally-admitted")
            },
        )
        self.jwt_issuer = SimpleNamespace(verify_token=lambda raw: {"client_id": "app"})
        self.register_client = AsyncMock()


@pytest.fixture
def gateway(tmp_path):
    store = UserStore(tmp_path / "state")
    principals = []
    for subject in ("alice", "bob"):
        uid = store.provision("issuer", subject, operator=True)
        store.grant(uid, "app", admin=True, views=["*"])
        principals.append(store.resolve(Identity("issuer", subject, "app")))

    def factory(config):
        upstream = FastMCP(config.command)

        @upstream.tool
        async def who() -> str:
            return config.command

        return Client(upstream)

    runtime = UserRuntime(store, client_factory=factory, base_url="https://proxy.test")
    app = UserGateway(runtime, FakeOAuth())
    yield app, *principals
    store.close()


def user_config(command):
    return {
        "mcp_servers": {"same": {"command": command}},
        "tool_views": {"default": {"include_all": True}},
    }


async def test_http_management_cannot_select_another_owner(gateway):
    app, alice, bob = gateway
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (await client.get("/health")).json() == {"status": "healthy"}
        assert (await client.get("/config/api/config")).status_code == 401
        for token in ("unknown", "accidentally-admitted"):
            assert (
                await client.get(
                    "/config/api/config", headers={"Authorization": f"Bearer {token}"}
                )
            ).status_code == 403
        client.headers["Authorization"] = "Bearer alice"
        preview = await client.post(
            "/config/api/preview",
            json={
                "base": None,
                "config": user_config("alice-private"),
                "user_id": bob.user_id,
            },
        )
        assert preview.status_code == 200
        revision = preview.json()["revision"]
        assert (
            await client.post("/config/api/apply", json={"revision": revision})
        ).status_code == 200
        assert (await client.get("/config/api/status")).json()[
            "runtime_revision"
        ] == revision
        assert (await client.get("/config/api/history")).json()["revisions"]
        assert "default" in (await client.get("/views")).json()["views"]
        client.headers["Authorization"] = "Bearer bob"
        assert (await client.get("/config/api/config")).json()["revision"] is None
        assert (
            await client.post("/config/api/apply", json={"revision": revision})
        ).status_code == 404
        assert (
            await client.post(
                "/config/api/rollback",
                json={
                    "base": None,
                    "target": revision,
                },
            )
        ).status_code == 404
        client.headers["Authorization"] = "Bearer alice"
        assert (
            await client.post("/config/api/preview", json={"base": None, "config": {}})
        ).status_code == 409
        assert (await client.post("/config/api/preview", json=[])).status_code == 400
        assert (await client.post("/config/api/preview", json={})).status_code == 400
        assert (await client.get("/config/api/absent")).status_code == 404
        assert (await client.post("/config/api/absent", json={})).status_code == 404
        assert (
            await client.post("/config/api/preview", content=b"x" * 1048577)
        ).status_code == 413
        probe = await client.post(
            "/config/api/probe", json={"revision": revision, "server": "same"}
        )
        assert probe.json()["state"] == "connected"
        rollback = await client.post(
            "/config/api/rollback", json={"base": revision, "target": revision}
        )
        assert rollback.status_code == 200
    await app.runtime.close()


async def test_provider_isolates_discovery_execution_and_stale_tools(gateway):
    app, alice, bob = gateway
    service = ConfigService(app.store)
    for principal, command in ((alice, "alice-private"), (bob, "bob-private")):
        revision = service.preview(principal, None, user_config(command))["revision"]
        await app.runtime.apply(principal, revision)
    provider = UserProvider(app.runtime)
    with principal_context(alice):
        tools = await provider.list_tools()
        assert await provider.get_tool("nonexistent") is None
        tool = next(t for t in tools if "who" in t.name)
        assert "alice-private" in str(await tool.run({}))
        assert (await provider.get_tool(tool.name)).name == tool.name
    with principal_context(bob):
        with pytest.raises(AccessDenied):
            await tool.run({})
        other = await provider.get_tool(tool.name)
        assert "bob-private" in str(await other.run({}))
    old, _ = app.store.active(alice)
    revision = service.preview(alice, old, user_config("changed"))["revision"]
    await app.runtime.apply(alice, revision)
    with principal_context(alice), pytest.raises(Conflict):
        await tool.run({})
    app.store.revoke(alice.user_id, "app")
    with principal_context(alice), pytest.raises(AccessDenied):
        await provider.list_tools()
    await app.runtime.close()


async def test_verified_downstream_client_and_missing_identity(gateway):
    app, alice, _ = gateway
    assert await verified_identity(app.auth, "alice") == alice.identity
    with pytest.raises(AccessDenied):
        await verified_identity(app.auth, "invalid")
    app.auth.tokens["no-subject"] = {"client_id": "app", "scopes": []}
    with pytest.raises(AccessDenied):
        await verified_identity(app.auth, "no-subject")


async def test_browser_session_requires_csrf_and_survives_reopen(gateway):
    app, alice, _ = gateway
    from mcp_proxy.user_gateway import COOKIE

    session = app.store.create_session(alice)
    cookie = app.cipher.encrypt(session.encode()).decode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (await client.get("/config")).status_code == 307
        client.cookies.set(COOKIE, "forged")
        assert (await client.get("/config/api/config")).status_code == 403
        client.cookies.set(COOKIE, cookie)
        assert (await client.get("/config")).status_code == 200
        assert (
            await client.post("/config/api/preview", json={"base": None, "config": {}})
        ).status_code == 403
        client.headers["Origin"] = "https://proxy.test"
        assert (
            await client.post("/config/api/preview", json={"base": None, "config": {}})
        ).status_code == 200
        assert (await client.post("/config/logout")).status_code == 303
        client.cookies.set(COOKIE, cookie)
        assert (await client.get("/config/api/config")).status_code == 403
    reopened = UserStore(app.store.directory)
    with pytest.raises(AccessDenied):
        reopened.session_principal(session)
    reopened.close()


async def test_mcp_route_auth_and_public_discovery(gateway):
    app, _, _ = gateway
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        for path in ("/mcp", "/mcp/", "/view/remote/mcp", "/search/mcp"):
            response = await client.post(path, json={})
            assert response.status_code == 401
            assert "resource_metadata" in response.headers["www-authenticate"]
        # The test verifier has no authorization-server routes; forwarding remains
        # the real FastMCP app's responsibility (covered with OIDC fixtures too).
        assert (await client.get("/unknown-public-path")).status_code == 404
        assert (await client.get("/views")).status_code == 401


async def rpc(client, path, method, params=None, request_id=1):
    response = await client.post(
        path,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        },
    )
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        import json

        messages = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        if (
            params
            and params.get("name") == "proxy_apply"
            and any(
                m.get("result", {}).get("structuredContent", {}).get("state")
                == "active"
                for m in messages
            )
        ):
            assert any(
                m.get("method") == "notifications/tools/list_changed" for m in messages
            )
        return next(message for message in messages if message.get("id") == request_id)
    return response.json()


async def test_wire_mcp_rechecks_owner_views_and_live_generations(gateway):
    app, alice, bob = gateway
    for principal, command in ((alice, "alice-only"), (bob, "bob-only")):
        value = user_config(command)
        value["tool_views"]["remote"] = {"include_all": True}
        draft = app.service.preview(principal, None, value)
        await app.runtime.apply(principal, draft["revision"])
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app),
            base_url="https://proxy.test",
            headers={"Authorization": "Bearer alice"},
        ) as client:
            initialized = await rpc(
                client,
                "/mcp",
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "isolation-test", "version": "1"},
                },
            )
            assert "result" in initialized
            for path in ("/mcp", "/view/remote/mcp"):
                discovery = await rpc(client, path, "tools/list")
                name = next(
                    t["name"]
                    for t in discovery["result"]["tools"]
                    if "who" in t["name"]
                )
                result = await rpc(client, path, "tools/call", {"name": name})
                assert "alice-only" in str(result)
                assert "bob-only" not in str(result)
            client.headers["Authorization"] = "Bearer bob"
            result = await rpc(client, "/mcp", "tools/call", {"name": name})
            assert "bob-only" in str(result)
            assert "alice-only" not in str(result)
            app.store.grant(bob.user_id, "app", views=["remote"])
            assert (await client.post("/mcp", json={})).status_code == 401
            assert "result" in await rpc(client, "/view/remote/mcp", "tools/list")
            app.store.revoke(bob.user_id, "app")
            assert (await client.post("/view/remote/mcp", json={})).status_code == 401


async def test_browser_callback_pkce_state_client_binding_and_assets(gateway):
    from urllib.parse import parse_qs, urlsplit

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mcp_proxy.user_gateway import BROWSER_CLIENT, COOKIE, LOGIN_COOKIE

    app, alice, _ = gateway
    app.store.grant(alice.user_id, BROWSER_CLIENT, admin=True, views=["default"])
    app.auth.jwt_issuer.verify_token = lambda raw: {"client_id": BROWSER_CLIENT}
    exchanges = []

    async def token(request):
        values = parse_qs((await request.body()).decode())
        exchanges.append(values)
        assert values["code_verifier"]
        assert values["client_id"] == [BROWSER_CLIENT]
        return JSONResponse({"access_token": "alice"})

    app.mcp_app = Starlette(routes=[Route("/token", token, methods=["POST"])])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (
            await client.get("/config/login/callback?state=forged&code=x")
        ).status_code == 400
        login = await client.get("/config/login")
        query = parse_qs(urlsplit(login.headers["location"]).query)
        state = query["state"][0]
        assert query["code_challenge_method"] == ["S256"]
        callback = f"/config/login/callback?state={state}&code=test"
        response = await client.get(callback)
        assert response.status_code == 303
        assert "Secure" in response.headers["set-cookie"]
        assert COOKIE in client.cookies
        assert (await client.get("/config/api/config")).status_code == 200
        client.cookies.set(LOGIN_COOKIE, state)
        assert (await client.get(callback)).status_code == 400
        assert len(exchanges) == 1
        ui = await client.get("/config")
        assert "frame-ancestors 'none'" in ui.headers["content-security-policy"]
        assert "/config/assets/app.js" in ui.text
        for name in ("app.js", "style.css"):
            assert (await client.get(f"/config/assets/{name}")).status_code == 200
        assert (await client.get("/config/assets/secret.key")).status_code == 404
        assert (await client.get("/config/logout")).status_code == 404
        assert (await client.post("/config/logout")).status_code == 403
        # A valid token issued for another app must never finish browser login.
        client.cookies.clear()
        login = await client.get("/config/login")
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        app.auth.jwt_issuer.verify_token = lambda raw: {"client_id": "app"}
        assert (
            await client.get(f"/config/login/callback?state={state}&code=x")
        ).status_code == 400


async def test_caches_require_both_owner_and_view(gateway, tmp_path, monkeypatch):
    from mcp_proxy.cache import create_cached_output_with_meta as create_cached_output

    app, alice, bob = gateway
    monkeypatch.setattr("mcp_proxy.cache.CACHE_DIR", tmp_path / "cache")
    cached = create_cached_output(
        "alice-private-output",
        app.runtime.cache_key(alice.user_id),
        "https://proxy.test/view/default",
        3600,
        10,
    )
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
        ) as client:
            assert (await client.get(cached.retrieve_url)).status_code == 401
            client.headers["Authorization"] = "Bearer alice"
            response = await client.get(cached.retrieve_url)
            assert response.status_code == 200
            assert "alice-private-output" in response.text
            for path in ("/mcp", "/search/mcp"):
                result = await rpc(
                    client, path, "resources/read", {"uri": "cache://" + cached.token}
                )
                assert ("alice-private-output" in str(result)) == (path == "/mcp")
            assert (
                await client.get(cached.retrieve_url.replace("/default/", "/absent/"))
            ).status_code == 404
            client.headers["Authorization"] = "Bearer bob"
            assert (await client.get(cached.retrieve_url)).status_code == 404
            result = await rpc(
                client, "/mcp", "resources/read", {"uri": "cache://" + cached.token}
            )
            assert "alice-private-output" not in str(result)
            app.store.grant(bob.user_id, "app", views=["default"])
            assert (await client.get("/views")).json()["views"] == ["default"]
            assert (await client.post("/config/api/apply", json={})).status_code == 403
            assert (await client.post("/config/logout")).status_code == 303


async def test_preparation_failure_http_redaction_and_stale_empty_generation(
    gateway, monkeypatch
):
    app, alice, _ = gateway
    provider = UserProvider(app.runtime)
    with principal_context(alice):
        empty_tool = (await provider.list_tools())[0]
    draft = app.service.preview(alice, None, user_config("valid"))
    await app.runtime.apply(alice, draft["revision"])
    with principal_context(alice), pytest.raises(Conflict):
        await empty_tool.run({})
    monkeypatch.setattr(
        app.runtime, "apply", AsyncMock(side_effect=RuntimeError("credential-marker"))
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app),
        base_url="https://proxy.test",
        headers={"Authorization": "Bearer alice"},
    ) as client:
        response = await client.post("/config/api/apply", json={"revision": "x"})
        assert response.status_code == 502
        assert "credential-marker" not in response.text
    await app.runtime.close()


def test_configured_gateway_requires_managed_state_and_oauth(tmp_path, monkeypatch):
    from unittest.mock import patch

    from mcp_proxy.user_gateway import configured_gateway, oauth_backend

    monkeypatch.delenv("MCP_PROXY_STATE_DIR", raising=False)
    with pytest.raises(ValueError, match="HTTP requires"):
        configured_gateway()
    monkeypatch.setenv("MCP_PROXY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_BASE_URL", "https://proxy.test")
    with (
        patch("mcp_proxy.auth.is_oidc_auth_configured", return_value=True),
        patch("mcp_proxy.auth.create_auth_provider", return_value=FakeOAuth()),
    ):
        gateway = configured_gateway()
        gateway.store.close()
    with (
        patch("mcp_proxy.auth.is_oidc_auth_configured", return_value=True),
        patch("mcp_proxy.auth.create_auth_provider", return_value=None),
        pytest.raises(ValueError, match="requires OAuth"),
    ):
        configured_gateway()
    assert (
        oauth_backend(SimpleNamespace(provider=SimpleNamespace(oidc_provider="inner")))
        == "inner"
    )


async def test_identity_bootstrap_reports_verified_client_without_grant(gateway):
    app, _, _ = gateway
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (await client.get("/config/api/identity")).status_code == 401
        client.headers["Authorization"] = "Bearer accidentally-admitted"
        response = await client.get("/config/api/identity")
        assert response.json() == {
            "issuer": "issuer",
            "subject": "accidentally-admitted",
            "client_id": "app",
            "email": None,
        }
        assert (await client.get("/config/api/config")).status_code == 403
        assert (await client.post("/mcp", json={})).status_code == 401


async def test_upstream_exception_details_do_not_escape_scope(gateway):
    from fastmcp.exceptions import ToolError

    app, alice, _ = gateway
    with principal_context(alice):
        tool = (await UserProvider(app.runtime).list_tools())[0]
        tool.inner = SimpleNamespace(
            run=AsyncMock(side_effect=RuntimeError("private-token"))
        )
        with pytest.raises(ToolError, match="Tool execution failed") as exc:
            await tool.run({})
        assert "private-token" not in str(exc.value)
        assert exc.value.__suppress_context__
    await app.runtime.close()


async def test_session_reports_own_grant(gateway):
    app, alice, _ = gateway
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (await client.get("/config/api/session")).status_code == 401
        client.headers["Authorization"] = "Bearer alice"
        response = await client.get("/config/api/session")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "identity": {
            "issuer": "issuer",
            "subject": "alice",
            "client_id": "app",
            "email": None,
        },
        "admin": True,
        "operator": True,
        "views": ["*"],
    }


async def test_users_manage_only_their_own_keys_within_their_grant(gateway):
    app, alice, bob = gateway
    narrow = app.store.provision("issuer", "accidentally-admitted")
    app.store.grant(narrow, "app", views=["default"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
    ) as client:
        assert (await client.get("/config/api/keys")).status_code == 401
        client.headers["Authorization"] = "Bearer alice"
        created = await client.post(
            "/config/api/keys",
            json={"name": "agent", "views": ["remote"], "expires_in": 3600},
        )
        assert created.status_code == 201
        key = created.json()
        assert key["token"].startswith("mcp_key_")
        assert key["expires"] is not None
        listed = (await client.get("/config/api/keys")).json()["keys"]
        assert [(k["id"], k["views"], k["admin"], k["revoked"]) for k in listed] == [
            (key["id"], ["remote"], False, False)
        ]
        assert "digest" not in listed[0] and "token" not in listed[0]

        client.headers["Authorization"] = "Bearer bob"
        assert (await client.get("/config/api/keys")).json() == {"keys": []}
        other = await client.delete(f"/config/api/keys/{key['id']}")
        assert other.status_code == 404

        # Keys never exceed the creating grant, and keys cannot mint keys.
        client.headers["Authorization"] = "Bearer accidentally-admitted"
        for body in (
            {"name": "x", "views": ["remote"]},
            {"name": "x", "views": ["default"], "admin": True},
        ):
            assert (await client.post("/config/api/keys", json=body)).status_code == 403
        client.headers["Authorization"] = "Bearer " + key["token"]
        assert (await client.get("/config/api/keys")).status_code == 403
        assert (await client.delete(f"/config/api/keys/{key['id']}")).status_code == 403

        client.headers["Authorization"] = "Bearer alice"
        revoked = await client.delete(f"/config/api/keys/{key['id']}")
        assert revoked.json() == {"status": "revoked"}
        listed = (await client.get("/config/api/keys")).json()["keys"]
        assert listed[0]["revoked"] is True and listed[0]["views"] == []
    with pytest.raises(AccessDenied):
        app.keys.identity(key["token"])


async def test_key_creation_rejects_invalid_requests(gateway):
    app, _, _ = gateway
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.app),
        base_url="https://proxy.test",
        headers={"Authorization": "Bearer alice"},
    ) as client:
        for body in (
            b"{",
            b"[]",
            b'{"name": 1, "views": ["default"]}',
            b'{"name": "x", "views": ["default"], "admin": "yes"}',
            b'{"name": "x", "views": []}',
            b'{"name": "x", "views": "default"}',
            b'{"name": "x", "views": [1]}',
            b'{"name": "x", "views": ["default"], "expires_in": 1.5}',
            b'{"name": "x", "views": ["default"], "expires_in": -1}',
            b'{"name": " ", "views": ["default"]}',
            b'{"name": "x"}',
            b"x" * 70000,
        ):
            response = await client.post("/config/api/keys", content=body)
            assert response.status_code == 400, body[:60]
        admin = await client.post(
            "/config/api/keys",
            json={"name": "admin", "views": ["default", "admin"], "admin": True},
        )
        assert admin.status_code == 201


def test_verified_email_is_best_effort(monkeypatch):
    from mcp_proxy.identity import verified_email

    assert verified_email({}) is None
    assert verified_email({"email": " "}) is None
    assert verified_email({"email": "a@x.test"}) is None
    assert verified_email({"email": " a@x.test ", "email_verified": True}) == (
        "a@x.test"
    )
    monkeypatch.setenv("MCP_PROXY_AUTH_REQUIRE_EMAIL_VERIFIED", "false")
    assert verified_email({"email": "a@x.test"}) == "a@x.test"
    token = SimpleNamespace(
        client_id="app",
        claims={"iss": "i", "sub": "s", "email": "a@x.test"},
    )
    identity = Identity.from_verified_token(token)
    assert identity.email == "a@x.test"
    assert identity == Identity("i", "s", "app")


def test_admin_email_list_grants_admin_by_matching_email(tmp_path, monkeypatch):
    from mcp_proxy.auth import get_admin_emails

    monkeypatch.setenv("MCP_PROXY_ADMIN_EMAILS", "Admin@X.test; other@x.test")
    assert get_admin_emails() == {"admin@x.test", "other@x.test"}
    store = UserStore(tmp_path / "state", admin_emails=get_admin_emails())
    uid = store.provision("issuer", "carol")
    store.grant(uid, "mcp-proxy-browser", views=["default"])

    without_email = store.resolve(Identity("issuer", "carol", "mcp-proxy-browser"))
    with pytest.raises(AccessDenied):
        store.authorize(without_email, admin=True)
    with pytest.raises(AccessDenied):
        store.create_session(without_email)
    assert store.access(without_email)["admin"] is False

    stranger = store.resolve(
        Identity("issuer", "carol", "mcp-proxy-browser", "nobody@x.test")
    )
    with pytest.raises(AccessDenied):
        store.authorize(stranger, admin=True)

    admin = store.resolve(
        Identity("issuer", "carol", "mcp-proxy-browser", "admin@x.test")
    )
    store.authorize(admin, admin=True)
    assert store.access(admin)["admin"] is True
    # Browser sessions remember the email, so they stay admin after sign-in.
    session = store.create_session(admin)
    restored = store.session_principal(session)
    assert restored.identity.email == "admin@x.test"
    store.authorize(restored, admin=True)
    store.close()


def test_existing_session_table_gains_email_column(tmp_path):
    import sqlite3

    UserStore(tmp_path / "state").close()
    db = sqlite3.connect(tmp_path / "state" / "users.sqlite3")
    db.executescript(
        "DROP TABLE sessions; CREATE TABLE sessions (id TEXT PRIMARY KEY, "
        "user_id TEXT NOT NULL, client TEXT NOT NULL, expires REAL NOT NULL);"
    )
    db.close()
    store = UserStore(tmp_path / "state")
    columns = {r[1] for r in store.db.execute("PRAGMA table_info(sessions)")}
    assert "email" in columns
    store.close()
