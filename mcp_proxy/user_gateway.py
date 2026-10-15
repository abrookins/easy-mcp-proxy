"""Stable HTTP/MCP gateway: every component is selected by verified OAuth user."""

import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from mcp_proxy.identity import (
    AccessDenied,
    Identity,
    current_principal,
    principal_context,
)
from mcp_proxy.managed_config import ConfigService
from mcp_proxy.state import encryption_key
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import Conflict, NotFound

COOKIE = "proxy_user_session"
LOGIN_COOKIE = "proxy_login_state"
BROWSER_CLIENT = "mcp-proxy-browser"


def configured_gateway():
    """HTTP serving never falls back to the legacy global configuration."""
    from mcp_proxy.auth import create_auth_provider, is_oidc_auth_configured
    from mcp_proxy.user_store import UserStore

    directory = os.environ.get("MCP_PROXY_STATE_DIR")
    if not directory or not is_oidc_auth_configured():
        raise ValueError("HTTP requires MCP_PROXY_STATE_DIR and complete OAuth setup")
    store = UserStore(Path(directory))
    try:
        runtime = UserRuntime(
            store, base_url=os.environ["FASTMCP_SERVER_AUTH_AUTH0_BASE_URL"]
        )
        return UserGateway(runtime, create_auth_provider())
    except BaseException:
        store.close()
        raise


def oauth_backend(provider):
    """Unwrap policy/composite wrappers without changing verification policy."""
    while hasattr(provider, "provider") or hasattr(provider, "oidc_provider"):
        provider = getattr(provider, "provider", None) or provider.oidc_provider
    return provider


async def verified_identity(provider, raw: str) -> Identity:
    # FastMCP's token swap returns the upstream application's client_id.
    # Grants must instead use the verified downstream MCP application's ID.
    try:
        access = await provider.verify_token(raw)
        if access is None:
            raise AccessDenied("Invalid or expired access token")
        backend = oauth_backend(provider)
        payload = backend.jwt_issuer.verify_token(raw)
        access = access.model_copy(update={"client_id": payload.get("client_id")})
        return Identity.from_verified_token(access)
    except Exception:
        raise AccessDenied("Invalid or expired OAuth identity") from None


class ScopedTool(Tool):
    inner: Any = Field(exclude=True)
    runtime: Any = Field(exclude=True)
    owner: str = Field(exclude=True)
    revision: str | None = Field(exclude=True)

    async def run(self, arguments: dict):
        principal = current_principal()
        if principal.user_id != self.owner:
            raise AccessDenied("Tool belongs to another user")
        async with self.runtime.lease(principal, self.revision) as generation:
            if generation.revision != self.revision:
                raise Conflict("Tools changed; refresh discovery")
            try:
                return await self.inner.run(arguments)
            except Exception:
                # Transport and hook exceptions can contain resolved arguments.
                raise ToolError(
                    "Upstream execution failed; inspect connection health"
                ) from None


class UserProvider(Provider):
    def __init__(self, runtime: UserRuntime, administration=None):
        super().__init__()
        self.runtime = runtime
        self.administration = administration

    def wrap(self, tool, generation):
        fields = {k: getattr(tool, k) for k in Tool.model_fields}
        return ScopedTool(
            **fields,
            inner=tool,
            runtime=self.runtime,
            owner=generation.user_id,
            revision=generation.revision,
        )

    async def _list_tools(self):
        principal = current_principal()
        if self.administration and principal.view == "admin":
            self.administration.principal()
            return await self.administration.mcp.list_tools()
        async with self.runtime.lease(principal) as generation:
            return [
                self.wrap(tool, generation)
                for tool in await generation.mcps[principal.view].list_tools()
            ]

    async def _get_tool(self, name, version=None):
        principal = current_principal()
        if self.administration and principal.view == "admin":
            self.administration.principal()
            return await self.administration.mcp.get_tool(name, version)
        async with self.runtime.lease(principal) as generation:
            tool = await generation.mcps[principal.view].get_tool(name, version)
            return self.wrap(tool, generation) if tool else None


class UserGateway:
    """OAuth endpoints remain stable while per-user config generations change."""

    def __init__(self, runtime: UserRuntime, auth):
        if auth is None:
            raise ValueError("User gateway requires OAuth authentication")
        self.runtime = runtime
        self.store = runtime.store
        self.service = ConfigService(self.store)
        self.auth = auth
        self.cipher = encryption_key(self.store.directory, "browser")
        from mcp_proxy.user_admin import APP_URI, Administration

        self.administration = Administration(runtime)
        self.mcp = FastMCP(
            "User MCP Proxy",
            auth=auth,
            providers=[UserProvider(runtime, self.administration)],
            mask_error_details=True,
        )

        @self.mcp.resource(
            APP_URI,
            mime_type="text/html;profile=mcp-app",
            meta={"ui": {"csp": {"connectDomains": [], "resourceDomains": []}}},
        )
        def administration_ui() -> str:
            return self.administration.html()

        @self.mcp.resource("cache://{token}")
        async def cached_output(token: str) -> str:
            from mcp_proxy.cache import build_cached_output_payload, retrieve_by_token

            principal = current_principal()
            async with self.runtime.lease(principal) as generation:
                value = retrieve_by_token(
                    token, self.runtime.cache_key(principal.user_id, principal.view)
                )
                if value is None:
                    raise NotFound("Cached output unavailable")
                return json.dumps(
                    build_cached_output_payload(
                        value, config=generation.proxy._get_default_cache_config()
                    )
                )

        self.mcp_app = self.mcp.http_app(path="/mcp", stateless_http=True)
        routes = [
            Route("/health", self.health),
            Route("/config/login", self.login),
            Route("/config/login/callback", self.callback),
            Route("/config/logout", self.logout, methods=["POST"]),
            Route("/config", self.ui),
            Route("/config/assets/{name}", self.asset),
            Route("/config/api/identity", self.identity),
            Route("/config/api/{action}", self.api, methods=["GET", "POST"]),
            Route("/views", self.views),
            Route("/view/{view}/cache/{token}", self.cache),
            Mount("/", app=self.dispatch),
        ]

        @asynccontextmanager
        async def lifespan(app):
            import fcntl

            with (self.store.directory / "runtime.lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.store.recover()
                async with self.mcp_app.lifespan(self.mcp_app):
                    try:
                        yield
                    finally:
                        await self.runtime.close()

        self.app = Starlette(routes=routes, lifespan=lifespan)

    async def health(self, request):
        return JSONResponse({"status": "healthy"})

    async def identity(self, request):
        """Let a new OAuth client identify itself for explicit operator grants."""
        from dataclasses import asdict

        try:
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                raise AccessDenied("OAuth required")
            identity = await verified_identity(self.auth, authorization[7:])
            return JSONResponse(asdict(identity), headers={"Cache-Control": "no-store"})
        except AccessDenied:
            return self.denied(request)

    async def principal(self, request: Request, view="default", *, browser=False):
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            identity = await verified_identity(self.auth, authorization[7:])
            return self.store.resolve(identity, view)
        if browser and (cookie := request.cookies.get(COOKIE)):
            try:
                session = self.cipher.decrypt(cookie.encode()).decode()
            except Exception:
                raise AccessDenied("Browser session invalid") from None
            principal = self.store.session_principal(session)
            if request.method != "GET":
                if request.headers.get("origin") != self.runtime.base_url:
                    raise AccessDenied("Same-origin browser request required")
            return replace(principal, view=view) if view is not None else principal
        raise AccessDenied("OAuth authentication required")

    async def dispatch(self, scope, receive, send):
        path = scope["path"].rstrip("/")
        if path == "/.well-known/oauth-protected-resource/mcp":
            # Keep old discovery links usable after the shared-resource migration.
            path = "/.well-known/oauth-protected-resource"
            scope = dict(scope, path=path, raw_path=path.encode())
        if path == "/mcp":
            view = "default"
        elif path == "/search/mcp":
            view = "search"
        elif path.startswith("/view/") and path.endswith("/mcp"):
            view = path[len("/view/") : -len("/mcp")]
        else:
            # This app contains only FastMCP's OAuth/discovery/MCP routes.
            await self.mcp_app(scope, receive, send)
            return
        try:
            principal = await self.principal(Request(scope), view)
            with principal_context(principal):
                rewritten = dict(scope, path="/mcp", raw_path=b"/mcp")
                await self.mcp_app(rewritten, receive, send)
        except (AccessDenied, ValueError):
            response = JSONResponse(
                {"error": "access_denied"},
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer resource_metadata="'
                    f"{self.runtime.base_url}"
                    '/.well-known/oauth-protected-resource"'
                },
            )
            await response(scope, receive, send)

    async def cache(self, request):
        from mcp_proxy.cache import create_cache_routes

        try:
            principal = await self.principal(
                request, request.path_params["view"], browser=True
            )
            async with self.runtime.lease(principal) as generation:
                routes = create_cache_routes(
                    self.runtime.cache_key(principal.user_id, principal.view),
                    config=generation.proxy._get_default_cache_config(),
                )
                return await routes[0].endpoint(request)
        except AccessDenied:
            return self.denied(request)
        except NotFound:
            return JSONResponse({"error": "not_found"}, status_code=404)

    async def views(self, request):
        try:
            principal = await self.principal(request, view=None)
            _, config = self.store.active(principal)
            names = set(config.get("tool_views", {})) | {"default", "search", "admin"}
            views = []
            for name in sorted(names):
                try:
                    self.store.authorize(
                        replace(principal, view=name), admin=name == "admin"
                    )
                    # Admin permission and explicit endpoint access are separate.
                    self.store.authorize(replace(principal, view=name))
                    views.append(name)
                except AccessDenied:
                    continue
            return JSONResponse({"views": views})
        except AccessDenied:
            return self.denied(request)

    async def api(self, request):
        try:
            principal = await self.principal(request, view=None, browser=True)
            self.store.authorize(principal, admin=True)
            action = request.path_params["action"]
            if request.method == "GET":
                if action == "config":
                    value = self.service.read(principal)
                elif action == "history":
                    value = {"revisions": self.store.history(principal)}
                elif action == "status":
                    value = self.runtime.status(principal)
                else:
                    raise NotFound("Unknown operation")
            else:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        return JSONResponse(
                            {"error": "body_too_large"}, status_code=413
                        )
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Object required")
                if action == "preview":
                    value = self.service.preview(
                        principal, data["base"], data["config"]
                    )
                elif action == "apply":
                    value = await self.runtime.apply(principal, data["revision"])
                elif action == "probe":
                    value = await self.runtime.probe(
                        principal, data["revision"], data["server"]
                    )
                elif action == "rollback":
                    value = self.service.rollback_preview(
                        principal, data["base"], data["target"]
                    )
                else:
                    raise NotFound("Unknown operation")
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except AccessDenied:
            return self.denied(request)
        except NotFound:
            return JSONResponse({"error": "not_found"}, status_code=404)
        except Conflict:
            return JSONResponse({"error": "revision_conflict"}, status_code=409)
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        except Exception:
            # Upstream errors may embed credentials or private command arguments.
            return JSONResponse({"error": "operation_failed"}, status_code=502)

    def denied(self, request):
        authenticated = request.headers.get("authorization") or request.cookies.get(
            COOKIE
        )
        return JSONResponse(
            {"error": "access_denied"},
            status_code=403 if authenticated else 401,
            headers={
                "WWW-Authenticate": 'Bearer resource_metadata="'
                f'{self.runtime.base_url}/.well-known/oauth-protected-resource"'
            },
        )

    async def login(self, request):
        backend = oauth_backend(self.auth)
        callback = self.runtime.base_url + "/config/login/callback"
        scopes = backend.required_scopes
        await backend.register_client(
            OAuthClientInformationFull(
                client_id=BROWSER_CLIENT,
                client_name="MCP Proxy administration",
                redirect_uris=[AnyUrl(callback)],
                grant_types=["authorization_code"],
                response_types=["code"],
                token_endpoint_auth_method="none",
                scope=" ".join(scopes) or None,
            )
        )
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        self.store.begin_login(state, verifier)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": BROWSER_CLIENT,
                "redirect_uri": callback,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                **({"scope": " ".join(scopes)} if scopes else {}),
                "resource": str(backend._get_resource_url()),
            }
        )
        response = RedirectResponse(self.runtime.base_url + "/authorize?" + query)
        response.set_cookie(
            LOGIN_COOKIE,
            state,
            max_age=600,
            httponly=True,
            secure=self.runtime.base_url.startswith("https:"),
            samesite="lax",
        )
        return response

    async def callback(self, request):
        try:
            state = request.query_params.get("state", "")
            if not state or not hmac.compare_digest(
                state, request.cookies.get(LOGIN_COOKIE, "")
            ):
                raise AccessDenied("Invalid OAuth state")
            verifier = self.store.consume_login(state)
            code = request.query_params["code"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.mcp_app),
                base_url=self.runtime.base_url,
            ) as client:
                result = await client.post(
                    "/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": BROWSER_CLIENT,
                        "code_verifier": verifier,
                        "redirect_uri": self.runtime.base_url
                        + "/config/login/callback",
                        "resource": str(oauth_backend(self.auth)._get_resource_url()),
                    },
                )
                result.raise_for_status()
                identity = await verified_identity(
                    self.auth, result.json()["access_token"]
                )
            if identity.client_id != BROWSER_CLIENT:
                raise AccessDenied("Incorrect browser OAuth client")
            principal = self.store.resolve(identity)
            session = self.store.create_session(principal)
            cookie = self.cipher.encrypt(session.encode()).decode()
            response = RedirectResponse("/config", status_code=303)
            response.set_cookie(
                COOKIE,
                cookie,
                max_age=86400,
                httponly=True,
                secure=self.runtime.base_url.startswith("https:"),
                samesite="lax",
            )
            response.delete_cookie(LOGIN_COOKIE)
            return response
        except Exception:
            return JSONResponse({"error": "login_failed"}, status_code=400)

    async def logout(self, request):
        try:
            await self.principal(request, browser=True)
            cookie = request.cookies.get(COOKIE, "")
            if cookie:
                self.store.logout(self.cipher.decrypt(cookie.encode()).decode())
            response = RedirectResponse("/config", status_code=303)
            response.delete_cookie(COOKIE)
            return response
        except AccessDenied:
            return JSONResponse({"error": "access_denied"}, status_code=403)

    async def ui(self, request):
        try:
            principal = await self.principal(request, browser=True)
            self.store.authorize(principal, admin=True)
        except AccessDenied:
            return RedirectResponse("/config/login")
        return HTMLResponse(
            (Path(__file__).parent / "admin_ui/index.html").read_text(),
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def asset(self, request):
        name = request.path_params["name"]
        types = {"app.js": "text/javascript", "style.css": "text/css"}
        if name not in types:
            return Response(status_code=404)
        return Response(
            (Path(__file__).parent / "admin_ui" / name).read_text(),
            media_type=types[name],
            headers={"X-Content-Type-Options": "nosniff"},
        )
