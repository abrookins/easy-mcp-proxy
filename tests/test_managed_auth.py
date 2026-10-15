"""Real OAuth handlers catch resource and browser-login integration failures."""

import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import ClientCode
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from joserfc.errors import JoseError

from mcp_proxy.auth import CompositeAuthProvider
from mcp_proxy.managed_auth import MigratingJWTIssuer, SharedResourceOAuth
from mcp_proxy.state import oauth_persistence
from mcp_proxy.user_gateway import BROWSER_CLIENT, COOKIE, UserGateway
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import UserStore


class ManagedProxy(SharedResourceOAuth, OAuthProxy):
    pass


@pytest.mark.parametrize("scopes", [[], ["read:tools"]])
async def test_browser_real_authorization_and_pkce_exchange(tmp_path, scopes):
    base = "https://proxy.test"
    store = UserStore(tmp_path / "state")
    uid = store.provision("issuer", "owner", operator=True)
    store.grant(uid, BROWSER_CLIENT, admin=True, views=["*"])
    verifier = StaticTokenVerifier(
        tokens={
            "upstream": {
                "client_id": "idp-app",
                "scopes": scopes,
                "iss": "issuer",
                "sub": "owner",
            }
        },
        required_scopes=scopes,
    )
    provider = ManagedProxy(
        upstream_authorization_endpoint="https://idp.test/authorize",
        upstream_token_endpoint="https://idp.test/token",
        upstream_client_id="idp-app",
        upstream_client_secret="test-only",
        token_verifier=verifier,
        base_url=base,
        require_authorization_consent=False,
        **oauth_persistence(store.directory),
    )
    # The deployed composite's required_scopes is deliberately empty. Browser
    # requests must use the actual OAuth backend's policy instead.
    auth = CompositeAuthProvider(oidc_provider=provider)
    gateway = UserGateway(UserRuntime(store, base_url=base), auth)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway.app), base_url=base
    ) as http:
        for path in ("/mcp", "/view/remote/mcp", "/search/mcp"):
            denied = await http.post(path, json={})
            metadata_url = denied.headers["www-authenticate"].split('"')[1]
            metadata = (await http.get(metadata_url)).json()
            assert metadata["resource"] == base + "/"
        old = await http.get("/.well-known/oauth-protected-resource/mcp")
        assert old.json() == metadata

        login = await http.get("/config/login")
        query = parse_qs(
            urlsplit(login.headers["location"]).query, keep_blank_values=True
        )
        assert query.get("scope") == ([" ".join(scopes)] if scopes else None)
        authorization = await http.get(login.headers["location"])
        assert urlsplit(authorization.headers["location"]).netloc == "idp.test"
        # Old discovery clients remain accepted; unrelated targets do not.
        query["resource"] = base + "/mcp"
        values = {k: v[0] if isinstance(v, list) else v for k, v in query.items()}
        old_authorization = await http.get("/authorize", params=values)
        assert urlsplit(old_authorization.headers["location"]).netloc == "idp.test"
        values["resource"] = "https://other.test/"
        refused = await http.get("/authorize", params=values)
        assert parse_qs(urlsplit(refused.headers["location"]).query)["error"] == [
            "server_error"  # SDK maps FastMCP's invalid_target to this error.
        ]

        # Model the IdP's completed exchange, then exercise the real /token
        # handler, PKCE validation, signed JWT verification and browser session.
        now = time.time()
        await provider._code_store.put(
            "browser-code",
            ClientCode(
                code="browser-code",
                client_id=BROWSER_CLIENT,
                redirect_uri=base + "/config/login/callback",
                code_challenge=query["code_challenge"][0],
                code_challenge_method="S256",
                scopes=scopes,
                idp_tokens={"access_token": "upstream", "expires_in": 3600},
                expires_at=now + 300,
                created_at=now,
            ),
        )
        callback = await http.get(
            "/config/login/callback",
            params={
                "state": query["state"][0],
                "code": "browser-code",
            },
        )
        assert callback.status_code == 303
        assert COOKIE in http.cookies
        assert (await http.get("/config/api/config")).status_code == 200
    store.close()


def test_audience_migration_preserves_all_token_checks():
    args = dict(issuer="https://proxy.test/", signing_key=b"a" * 32)
    issuer = MigratingJWTIssuer(
        **args,
        audience="https://proxy.test/",
        legacy_audience="https://proxy.test/mcp",
    )
    for audience in ("https://proxy.test/", "https://proxy.test/mcp"):
        old = JWTIssuer(**args, audience=audience)
        access = old.issue_access_token("client", [], "access")
        refresh = old.issue_refresh_token("client", [], "refresh", 3600)
        assert issuer.verify_token(access)["aud"] == audience
        assert issuer.verify_token(refresh, "refresh")["aud"] == audience
        for token, use in ((refresh, "access"), (access, "refresh")):
            with pytest.raises(JoseError):
                issuer.verify_token(token, use)
        with pytest.raises(JoseError):
            issuer.verify_token(old.issue_access_token("client", [], "expired", -1))
    for overrides in (
        {"audience": "https://other.test/"},
        {"issuer": "https://other.test/"},
        {"signing_key": b"b" * 32},
    ):
        other = JWTIssuer(**{**args, "audience": "https://proxy.test/", **overrides})
        with pytest.raises(JoseError):
            issuer.verify_token(other.issue_access_token("client", [], "wrong"))
    assert (
        issuer.verify_token(issuer.issue_access_token("client", [], "new"))["aud"]
        == "https://proxy.test/"
    )
