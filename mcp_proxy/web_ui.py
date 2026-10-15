"""Web UI for managing MCP Proxy configuration.

Serves a small single-page app plus the JSON API it uses. Configuration is
loaded from the YAML file the proxy was started with, and edits are saved as
overrides to a JSON file next to it.

Authentication:
- Browsers sign in with the configured OIDC provider and get a session cookie
- API clients use Bearer tokens like other endpoints
- Only users whose email is in the config's `admins` list can change config
- When no auth is configured, every request is treated as an admin
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_module
import json
import os
import secrets
import signal
import time
import urllib.parse
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import yaml
from pydantic import ValidationError
from rapidfuzz import fuzz, process
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Route

from mcp_proxy.config import _deep_merge, compute_overrides
from mcp_proxy.models import ProxyConfig
from mcp_proxy.utils import substitute_env_vars

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AuthProvider

    from mcp_proxy.api_keys import ApiKeyStore
    from mcp_proxy.proxy import MCPProxy

# Session cookie settings
SESSION_COOKIE_NAME = "mcp_proxy_session"
SESSION_MAX_AGE = 3600 * 24  # 24 hours
STATE_COOKIE_NAME = "mcp_proxy_oauth_state"
STATE_MAX_AGE = 600
LOGIN_SCOPES = "openid email profile"
CSRF_HEADER = "X-MCP-Proxy-UI"
STATIC_FILES = {"app.js": "text/javascript", "app.css": "text/css"}

# Used when no client secret is configured (sessions won't survive restart)
_FALLBACK_SESSION_SECRET = secrets.token_hex(32)


def build_error_html(title: str, message: str) -> str:
    """Build a simple escaped error page."""
    return (
        f"<!DOCTYPE html><title>{html_module.escape(title)}</title>"
        f"<h1>{html_module.escape(title)}</h1><p>{html_module.escape(message)}</p>"
    )


def _error_response(title: str, message: str, status_code: int = 500) -> HTMLResponse:
    """Create an HTML error response."""
    return HTMLResponse(build_error_html(title, message), status_code=status_code)


def get_config_path() -> Path:
    """Get the config file path from environment or default."""
    return Path(os.environ.get("MCP_PROXY_CONFIG", "config.yaml"))


def get_overrides_path(config_path: Path) -> Path:
    """Get the path for the overrides file (JSON next to YAML)."""
    return config_path.with_suffix(".overrides.json")


def load_raw_config(config_path: Path) -> dict[str, Any]:
    """Load the raw YAML config."""
    if not config_path.exists():
        return {"mcp_servers": {}, "tool_views": {}}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_overrides(config_path: Path) -> dict[str, Any]:
    """Load saved overrides."""
    overrides_path = get_overrides_path(config_path)
    if not overrides_path.exists():
        return {}
    with open(overrides_path) as f:
        return json.load(f)


def save_overrides(config_path: Path, overrides: dict[str, Any]) -> None:
    """Save overrides to JSON file."""
    with open(get_overrides_path(config_path), "w") as f:
        json.dump(overrides, f, indent=2)


def load_merged_config(config_path: Path) -> dict[str, Any]:
    """Load config with overrides merged in."""
    return _deep_merge(load_raw_config(config_path), load_overrides(config_path))


def save_config(config_path: Path, new_config: dict[str, Any]) -> None:
    """Validate and save a complete config as overrides of the YAML file."""
    ProxyConfig(**substitute_env_vars(new_config))
    base = load_raw_config(config_path)
    save_overrides(config_path, compute_overrides(base, new_config))


def _get_session_secret() -> str:
    """Get the secret for signing session cookies."""
    from mcp_proxy.auth import AUTH0_CLIENT_SECRET_VAR

    return os.environ.get(AUTH0_CLIENT_SECRET_VAR) or _FALLBACK_SESSION_SECRET


def _sign_session_data(data: str) -> str:
    """Sign data with HMAC-SHA256."""
    secret = _get_session_secret()
    signature = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{signature}"


def _verify_session_data(signed_data: str) -> str | None:
    """Verify signed data. Returns the data if valid, None otherwise."""
    if "." not in signed_data:
        return None
    data, signature = signed_data.rsplit(".", 1)
    expected = _sign_session_data(data).rsplit(".", 1)[1]
    if hmac.compare_digest(signature, expected):
        return data
    return None


def _create_signed_cookie(payload: dict[str, Any], max_age: int) -> str:
    """Sign a JSON payload, base64-encoded so it is a valid cookie value."""
    data = json.dumps({**payload, "expires": int(time.time()) + max_age})
    return _sign_session_data(base64.urlsafe_b64encode(data.encode()).decode())


def _verify_signed_cookie(cookie_value: str) -> dict[str, Any] | None:
    data = _verify_session_data(cookie_value)
    if not data:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(data))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("expires", 0) < time.time():
        return None
    return payload


def create_session_cookie(user_id: str, email: str | None = None) -> str:
    """Create a signed session cookie value."""
    return _create_signed_cookie({"user_id": user_id, "email": email}, SESSION_MAX_AGE)


def verify_session_cookie(cookie_value: str) -> dict[str, Any] | None:
    """Verify a session cookie. Returns session data if valid, None otherwise."""
    return _verify_signed_cookie(cookie_value)


def is_browser_request(request: Request) -> bool:
    """Check if request appears to be from a browser (vs API client)."""
    return "text/html" in request.headers.get("Accept", "")


def _safe_return_url(url: str, default: str) -> str:
    """Only allow same-origin relative return URLs."""
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default


def _get_oidc_provider(auth_provider: "AuthProvider | None") -> Any | None:
    """Find the OIDC provider (with discovered endpoints) inside auth wrappers."""
    provider: Any = auth_provider
    while provider is not None and not hasattr(provider, "oidc_config"):
        provider = getattr(provider, "oidc_provider", None) or getattr(
            provider, "provider", None
        )
    return provider


def _get_restricted_provider(auth_provider: "AuthProvider | None") -> Any | None:
    """Find a RestrictedAuthProvider inside auth wrappers, if any."""
    from mcp_proxy.auth import RestrictedAuthProvider

    provider: Any = auth_provider
    if provider is not None and not isinstance(provider, RestrictedAuthProvider):
        provider = getattr(provider, "oidc_provider", None)
    return provider if isinstance(provider, RestrictedAuthProvider) else None


def _get_oauth_credentials() -> tuple[str, str]:
    """Get the OAuth client ID and secret from the environment."""
    from mcp_proxy.auth import AUTH0_CLIENT_ID_VAR, AUTH0_CLIENT_SECRET_VAR

    return (
        os.environ.get(AUTH0_CLIENT_ID_VAR, ""),
        os.environ.get(AUTH0_CLIENT_SECRET_VAR, ""),
    )


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT claims without verification.

    Only used for ID tokens received directly from the token endpoint over
    TLS, which OIDC Core 3.1.3.7 allows in place of signature validation.
    """
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


async def _exchange_code_for_claims(
    oidc_config: Any, code: str, redirect_uri: str
) -> dict[str, Any] | None:
    """Exchange an authorization code and return the user's identity claims."""
    import httpx

    client_id, client_secret = _get_oauth_credentials()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                str(oidc_config.token_endpoint),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                return None
            tokens = response.json()
            claims = _decode_jwt_claims(tokens.get("id_token", ""))
            if oidc_config.userinfo_endpoint and tokens.get("access_token"):
                userinfo = await client.get(
                    str(oidc_config.userinfo_endpoint),
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                )
                if userinfo.status_code == 200:
                    claims.update(userinfo.json())
    except (httpx.HTTPError, ValueError):
        return None
    return claims


@dataclass
class Identity:
    """The user making a web UI request."""

    email: str | None
    auth_enabled: bool = True
    via_session: bool = False

    def is_admin(self, admins: list[str]) -> bool:
        if not self.auth_enabled:
            return True
        allowed = {admin.casefold() for admin in admins}
        return self.email is not None and self.email.casefold() in allowed


Handler = Callable[[Request, Identity], Awaitable[Response]]


def create_web_ui_routes(
    path_prefix: str = "/config",
    auth_provider: "AuthProvider | None" = None,
    proxy: "MCPProxy | None" = None,
    config_path: Path | None = None,
    api_key_store: "ApiKeyStore | None" = None,
) -> list[Route]:
    """Create web UI routes for config management.

    Args:
        path_prefix: URL prefix for config routes
        auth_provider: Auth provider used for Bearer tokens and browser login
        proxy: Live proxy, used for the tool registry and upstream tool lists
        config_path: YAML config file to edit (defaults to MCP_PROXY_CONFIG)
        api_key_store: Store for user-owned API keys

    Returns:
        List of Starlette routes
    """

    def current_config_path() -> Path:
        return config_path or get_config_path()

    def current_admins() -> list[str]:
        return list(load_merged_config(current_config_path()).get("admins") or [])

    async def get_identity(request: Request) -> Identity | None:
        if auth_provider is None:
            return Identity(email=None, auth_enabled=False)
        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if session_cookie:
            session = verify_session_cookie(session_cookie)
            if session:
                return Identity(email=session.get("email"), via_session=True)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:]:
            access_token = await auth_provider.verify_token(auth_header[7:])
            if access_token is not None:
                claims = getattr(access_token, "claims", {}) or {}
                email = claims.get("email")
                return Identity(email=email if isinstance(email, str) else None)
        return None

    def unauthenticated(request: Request) -> Response:
        if is_browser_request(request):
            return_url = urllib.parse.quote(request.url.path)
            return RedirectResponse(
                f"{path_prefix}/login?return_url={return_url}", status_code=302
            )
        return JSONResponse(
            {"error": "invalid_token", "error_description": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def authenticated(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            identity = await get_identity(request)
            if identity is None:
                return unauthenticated(request)
            if (
                identity.via_session
                and request.method not in ("GET", "HEAD")
                and request.headers.get(CSRF_HEADER) != "1"
            ):
                # Custom headers can't be sent cross-site without CORS approval
                return JSONResponse(
                    {"error": "forbidden", "message": f"Missing {CSRF_HEADER}."},
                    status_code=403,
                )
            return await handler(request, identity)

        return endpoint

    def admin_only(handler: Handler) -> Callable[[Request], Awaitable[Response]]:
        async def check_admin(request: Request, identity: Identity) -> Response:
            if not identity.is_admin(current_admins()):
                return JSONResponse(
                    {
                        "error": "forbidden",
                        "message": "Only admins can change configuration.",
                    },
                    status_code=403,
                )
            return await handler(request, identity)

        return authenticated(check_admin)

    def user_email(identity: Identity) -> str | None:
        return identity.email.casefold() if identity.email else None

    async def index(request: Request, identity: Identity) -> Response:
        prefix = html_module.escape(path_prefix, quote=True)
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MCP Proxy</title><link rel="stylesheet" href="{prefix}/static/app.css">
</head><body><div id="app" data-prefix="{prefix}">Loading…</div>
<script src="{prefix}/static/app.js"></script></body></html>""")

    async def static_file(request: Request) -> Response:
        name = request.path_params["name"]
        if name not in STATIC_FILES:
            return PlainTextResponse("Not found", status_code=404)
        content = resources.files("mcp_proxy").joinpath("web_static", name)
        return Response(content.read_text(), media_type=STATIC_FILES[name])

    async def me(request: Request, identity: Identity) -> Response:
        return JSONResponse(
            {
                "email": identity.email,
                "is_admin": identity.is_admin(current_admins()),
                "auth_enabled": identity.auth_enabled,
                "api_keys_enabled": api_key_store is not None
                and user_email(identity) is not None,
            }
        )

    async def get_config_json(request: Request, identity: Identity) -> Response:
        return JSONResponse(load_merged_config(current_config_path()))

    def validation_error(error: Exception) -> JSONResponse:
        if isinstance(error, ValidationError):
            details = [
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()
            ]
        else:
            details = [str(error)]
        return JSONResponse(
            {"error": "invalid_config", "details": details}, status_code=400
        )

    async def update_config_json(request: Request, identity: Identity) -> Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Configuration must be an object")
            save_config(current_config_path(), body)
        except (ValueError, ValidationError) as e:
            return validation_error(e)
        return JSONResponse({"status": "saved"})

    async def get_config_yaml(request: Request, identity: Identity) -> Response:
        merged = load_merged_config(current_config_path())
        return PlainTextResponse(
            yaml.dump(merged, default_flow_style=False, sort_keys=False)
        )

    async def update_config_yaml(request: Request, identity: Identity) -> Response:
        try:
            body = yaml.safe_load(await request.body())
            if not isinstance(body, dict):
                raise ValueError("Configuration must be a YAML mapping")
            save_config(current_config_path(), body)
        except (ValueError, ValidationError, yaml.YAMLError) as e:
            return validation_error(e)
        return JSONResponse({"status": "saved"})

    async def upstream_tools(request: Request, identity: Identity) -> Response:
        tools = proxy._upstream_tools if proxy is not None else {}
        return JSONResponse(
            {
                server: [
                    {"name": tool.name, "description": tool.description or ""}
                    for tool in server_tools
                ]
                for server, server_tools in tools.items()
            }
        )

    async def get_tool_registry(request: Request, identity: Identity) -> Response:
        """Return canonical exposed metadata for one view without executing tools."""
        if proxy is None:
            return JSONResponse(
                {
                    "error": "registry_unavailable",
                    "message": "The live tool registry is unavailable.",
                },
                status_code=503,
            )
        view_name = request.query_params.get("view") or "default"
        try:
            snapshot = proxy.get_registry_snapshot(view_name)
        except ValueError:
            choices = proxy.registry_view_names()
            payload: dict[str, Any] = {
                "error": "unknown_view",
                "message": f"View '{view_name}' not found.",
                "view": view_name,
                "available_view_names": choices,
            }
            match = process.extractOne(view_name, choices, scorer=fuzz.ratio)
            if match is not None and match[1] >= 70:
                payload["did_you_mean"] = match[0]
            return JSONResponse(payload, status_code=404)
        return JSONResponse(snapshot)

    def keys_unavailable() -> JSONResponse:
        return JSONResponse(
            {
                "error": "api_keys_unavailable",
                "message": "API keys require a signed-in user with an email.",
            },
            status_code=400,
        )

    async def list_keys(request: Request, identity: Identity) -> Response:
        owner = user_email(identity)
        if api_key_store is None or owner is None:
            return keys_unavailable()
        return JSONResponse({"keys": api_key_store.list_for(owner)})

    async def create_key(request: Request, identity: Identity) -> Response:
        owner = user_email(identity)
        if api_key_store is None or owner is None:
            return keys_unavailable()
        try:
            body = await request.json()
        except ValueError:
            body = None
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name.strip():
            return JSONResponse(
                {"error": "invalid_request", "message": "A key name is required."},
                status_code=400,
            )
        record, key = api_key_store.create(owner, name.strip())
        return JSONResponse({**record, "key": key}, status_code=201)

    async def revoke_key(request: Request, identity: Identity) -> Response:
        owner = user_email(identity)
        if api_key_store is None or owner is None:
            return keys_unavailable()
        if not api_key_store.revoke(owner, request.path_params["key_id"]):
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse({"status": "revoked"})

    async def restart_server(request: Request, identity: Identity) -> Response:
        """Trigger server restart (a process manager is expected to restart us)."""
        restart_marker = current_config_path().parent / ".mcp-proxy-restart"
        try:
            restart_marker.write_text("restart")
        except OSError:
            pass  # Not critical if this fails
        try:
            os.kill(os.getpid(), signal.SIGHUP)
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"status": "restart_initiated"})

    async def login_page(request: Request) -> Response:
        """Redirect to the OIDC provider's authorization endpoint."""
        provider = _get_oidc_provider(auth_provider)
        if provider is None:
            return _error_response(
                "Sign-in Not Configured",
                "Browser sign-in requires OIDC. Configure the OIDC environment "
                "variables, or use a Bearer token with the API.",
            )
        return_url = _safe_return_url(
            request.query_params.get("return_url", path_prefix), path_prefix
        )
        state = secrets.token_urlsafe(24)
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": _get_oauth_credentials()[0],
                "redirect_uri": str(request.url_for("config_login_callback")),
                "scope": LOGIN_SCOPES,
                "state": state,
            }
        )
        response = RedirectResponse(
            f"{provider.oidc_config.authorization_endpoint}?{query}", status_code=302
        )
        response.set_cookie(
            STATE_COOKIE_NAME,
            _create_signed_cookie(
                {"state": state, "return_url": return_url}, STATE_MAX_AGE
            ),
            max_age=STATE_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
        return response

    async def login_callback(request: Request) -> Response:
        """Handle the OIDC callback: verify state, fetch identity, set session."""
        code = request.query_params.get("code")
        if not code:
            error = request.query_params.get("error", "Unknown error")
            return _error_response("Login Failed", f"Error: {error}", 400)

        saved = _verify_signed_cookie(request.cookies.get(STATE_COOKIE_NAME, ""))
        state = request.query_params.get("state", "")
        if not saved or not hmac.compare_digest(str(saved.get("state")), state):
            return _error_response(
                "Login Failed", "Login session expired. Please try again.", 400
            )

        provider = _get_oidc_provider(auth_provider)
        if provider is None:
            return _error_response("Sign-in Not Configured", "OIDC is not configured.")

        callback_url = str(request.url_for("config_login_callback"))
        claims = await _exchange_code_for_claims(
            provider.oidc_config, code, callback_url
        )
        if claims is None:
            return _error_response(
                "Token Exchange Failed",
                "Could not exchange authorization code for token.",
            )

        restricted = _get_restricted_provider(auth_provider)
        if restricted is not None and not restricted._is_token_allowed(
            SimpleNamespace(claims=claims)
        ):
            return _error_response(
                "Access Denied", "Your account is not allowed to use this proxy.", 403
            )

        email = claims.get("email")
        email = email if isinstance(email, str) else None
        session_value = create_session_cookie(
            str(claims.get("sub") or email or "user"), email
        )
        response = RedirectResponse(str(saved["return_url"]), status_code=302)
        response.delete_cookie(STATE_COOKIE_NAME)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_value,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
        return response

    async def logout(request: Request) -> Response:
        """Log out by clearing the session cookie."""
        response = RedirectResponse(f"{path_prefix}/signed-out", status_code=302)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    async def signed_out(request: Request) -> Response:
        prefix = html_module.escape(path_prefix, quote=True)
        return HTMLResponse(
            "<!DOCTYPE html><title>Signed out</title><h1>Signed out</h1>"
            f'<p><a href="{prefix}">Sign in again</a></p>'
        )

    p = path_prefix
    return [
        Route(p, authenticated(index), methods=["GET"]),
        Route(f"{p}/static/{{name}}", static_file, methods=["GET"]),
        Route(f"{p}/api/me", authenticated(me), methods=["GET"]),
        Route(f"{p}/api", admin_only(get_config_json), methods=["GET"]),
        Route(f"{p}/api", admin_only(update_config_json), methods=["PUT"]),
        Route(f"{p}/api/yaml", admin_only(get_config_yaml), methods=["GET"]),
        Route(f"{p}/api/yaml", admin_only(update_config_yaml), methods=["PUT"]),
        Route(
            f"{p}/api/upstream-tools", authenticated(upstream_tools), methods=["GET"]
        ),
        Route(f"{p}/api/tools", authenticated(get_tool_registry), methods=["GET"]),
        Route(f"{p}/tools", authenticated(get_tool_registry), methods=["GET"]),
        Route(f"{p}/api/keys", authenticated(list_keys), methods=["GET"]),
        Route(f"{p}/api/keys", authenticated(create_key), methods=["POST"]),
        Route(
            f"{p}/api/keys/{{key_id}}", authenticated(revoke_key), methods=["DELETE"]
        ),
        Route(f"{p}/restart", admin_only(restart_server), methods=["POST"]),
        Route(f"{p}/login", login_page, methods=["GET"]),
        Route(
            f"{p}/login/callback",
            login_callback,
            methods=["GET"],
            name="config_login_callback",
        ),
        Route(f"{p}/logout", logout, methods=["GET", "POST"]),
        Route(f"{p}/signed-out", signed_out, methods=["GET"]),
    ]
