"""Process fixture with real OAuth persistence and a mocked identity provider."""

import asyncio
import hashlib
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
)
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from mcp_proxy.identity import Identity
from mcp_proxy.managed_auth import SharedResourceOAuth
from mcp_proxy.state import encryption_key, oauth_persistence
from mcp_proxy.user_gateway import UserGateway, verified_identity
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import UserStore


async def main(directory: Path, mode: str):
    base = "https://proxy.test"
    verifier = StaticTokenVerifier(
        tokens={
            "upstream-test-only": {
                "client_id": "idp-app",
                "scopes": [],
                "iss": "issuer",
                "sub": "owner",
            },
        }
    )

    class ManagedProxy(SharedResourceOAuth, OAuthProxy):
        pass

    provider_class = OAuthProxy if mode == "seed" else ManagedProxy
    provider = provider_class(
        upstream_authorization_endpoint="https://idp.test/authorize",
        upstream_token_endpoint="https://idp.test/token",
        upstream_client_id="idp-app",
        upstream_client_secret="fixture-only",
        token_verifier=verifier,
        base_url=base,
        **oauth_persistence(directory),
    )
    provider.get_routes(mcp_path="/mcp")
    store = UserStore(directory)
    path = directory / "fixture.json"
    if mode == "seed":
        uid = store.provision("issuer", "owner")
        store.grant(uid, "client", admin=True, views=["*"])
        principal = store.resolve(Identity("issuer", "owner", "client"))
        session = store.create_session(principal)
        browser = (
            encryption_key(directory, "browser").encrypt(session.encode()).decode()
        )
        client = OAuthClientInformationFull(
            client_id="client",
            redirect_uris=[AnyUrl("http://localhost/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        )
        await provider.register_client(client)
        now = time.time()
        await provider._upstream_token_store.put(
            "upstream",
            UpstreamTokenSet(
                upstream_token_id="upstream",
                access_token="upstream-test-only",
                refresh_token="refresh-upstream-test",
                refresh_token_expires_at=None,
                expires_at=now + 3600,
                token_type="Bearer",
                scope="",
                client_id="client",
                created_at=now,
            ),
        )
        access = provider.jwt_issuer.issue_access_token("client", [], "access")
        refresh = provider.jwt_issuer.issue_refresh_token(
            "client", [], "refresh", 86400
        )
        for jti in ("access", "refresh"):
            await provider._jti_mapping_store.put(
                jti, JTIMapping(jti=jti, upstream_token_id="upstream", created_at=now)
            )
        await provider._refresh_token_store.put(
            hashlib.sha256(refresh.encode()).hexdigest(),
            RefreshTokenMetadata(client_id="client", scopes=[], created_at=now),
        )
        path.write_text(
            json.dumps({"access": access, "refresh": refresh, "browser": browser})
        )
        path.chmod(0o600)
        print(json.dumps({"state": "seeded"}))
    else:
        data = json.loads(path.read_text())
        assert (await verified_identity(provider, data["access"])).subject == "owner"
        session = (
            encryption_key(directory, "browser")
            .decrypt(data["browser"].encode())
            .decode()
        )
        assert store.session_principal(session).identity.subject == "owner"
        client = await provider.get_client("client")
        refresh = await provider.load_refresh_token(client, data["refresh"])
        assert refresh is not None

        class Upstream:
            async def refresh_token(self, **kwargs):
                assert kwargs["refresh_token"] == "refresh-upstream-test"
                return {
                    "access_token": "upstream-test-only",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                }

        @asynccontextmanager
        async def upstream():
            yield Upstream()

        provider._upstream_oauth_client = upstream
        refreshed = await provider.exchange_refresh_token(client, refresh, [])
        assert (
            await verified_identity(provider, refreshed.access_token)
        ).subject == "owner"
        gateway = UserGateway(UserRuntime(store, base_url=base), provider)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway.app), base_url=base
        ) as http:
            metadata = await http.get("/.well-known/oauth-protected-resource/mcp")
            assert metadata.status_code == 200
            assert metadata.json()["resource"] == base + "/"
            for endpoint in ("/mcp", "/view/work/mcp"):
                denied = await http.post(endpoint, json={})
                assert denied.status_code == 401
                assert (
                    base + "/.well-known/oauth-protected-resource"
                    in denied.headers["www-authenticate"]
                )
        # Revocation is distinct from restarting or losing a transport session.
        loaded = await provider.load_refresh_token(client, refreshed.refresh_token)
        await provider.revoke_token(loaded)
        assert (
            await provider.load_refresh_token(client, refreshed.refresh_token) is None
        )
        store.revoke(
            store.resolve(Identity("issuer", "owner", "client")).user_id, "client"
        )
        assert await provider.load_access_token(refreshed.access_token) is not None
        print(
            json.dumps(
                {
                    "access": "passed",
                    "refresh": "passed",
                    "browser": "passed",
                    "discovery": "passed",
                }
            )
        )
    store.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2]))
