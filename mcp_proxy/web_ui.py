"""Web UI for editing MCP Proxy configuration.

Provides a simple web interface for editing the proxy configuration.
Configuration is loaded from the YAML file and overrides are saved
to a JSON file next to the YAML file.

Authentication:
- For browser access: Uses cookies with OAuth flow (redirects to login)
- For API access: Uses Bearer tokens like other endpoints
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import signal
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import yaml
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AuthProvider

# Type alias for auth check function
AuthChecker = Callable[[Request], Coroutine[Any, Any, Response | None]]

# Session cookie settings
SESSION_COOKIE_NAME = "mcp_proxy_session"
SESSION_MAX_AGE = 3600 * 24  # 24 hours

# HTML template parts - split to avoid line length issues
_CSS_STYLES = """
body { font-family: -apple-system, sans-serif; max-width: 1200px;
       margin: 0 auto; padding: 20px; background: #f5f5f5; }
h1 { color: #333; }
.card { background: white; border-radius: 8px; padding: 20px;
        margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.card h2 { margin-top: 0; color: #555;
           border-bottom: 1px solid #eee; padding-bottom: 10px; }
.form-group { margin-bottom: 15px; }
label { display: block; margin-bottom: 5px; font-weight: 600; color: #444; }
input[type="text"], textarea { width: 100%; padding: 10px;
    border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
textarea { font-family: monospace; min-height: 200px; }
button { background: #007bff; color: white; border: none;
         padding: 10px 20px; border-radius: 4px;
         cursor: pointer; margin-right: 10px; }
button:hover { background: #0056b3; }
button.danger { background: #dc3545; }
button.danger:hover { background: #c82333; }
.alert { padding: 15px; border-radius: 4px; margin-bottom: 20px; }
.alert-success { background: #d4edda; color: #155724; }
.alert-error { background: #f8d7da; color: #721c24; }
.server-item, .view-item { border: 1px solid #eee; padding: 15px;
                           margin-bottom: 10px; border-radius: 4px; }
.server-item h3, .view-item h3 { margin-top: 0; }
code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; }
.tabs { display: flex; border-bottom: 1px solid #ddd; margin-bottom: 20px; }
.tab { padding: 10px 20px; cursor: pointer; border: none; background: none; }
.tab.active { border-bottom: 2px solid #007bff; color: #007bff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
"""

_JS_SCRIPT = """
function showTab(name) {
    document.querySelectorAll('.tab').forEach(
        function(t) { t.classList.remove('active'); }
    );
    document.querySelectorAll('.tab-content').forEach(
        function(t) { t.classList.remove('active'); }
    );
    document.querySelector('[onclick*="' + name + '"]')
        .classList.add('active');
    document.getElementById(name).classList.add('active');
}
"""


def _build_html_template(
    alert: str,
    servers_html: str,
    views_html: str,
    config_yaml: str,
    save_url: str,
    restart_url: str,
) -> str:
    """Build the HTML page from parts."""
    restart_js = f"if(confirm('Restart?')) window.location='{restart_url}'"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Proxy Configuration</title>
    <style>{_CSS_STYLES}</style>
</head>
<body>
    <h1>MCP Proxy Configuration</h1>
    {alert}
    <div class="tabs">
        <button class="tab active" onclick="showTab('servers')">Servers</button>
        <button class="tab" onclick="showTab('views')">Views</button>
        <button class="tab" onclick="showTab('yaml')">YAML Editor</button>
    </div>
    <div id="servers" class="tab-content active">
        <div class="card">
            <h2>Upstream MCP Servers</h2>
            {servers_html}
        </div>
    </div>
    <div id="views" class="tab-content">
        <div class="card">
            <h2>Tool Views</h2>
            {views_html}
        </div>
    </div>
    <div id="yaml" class="tab-content">
        <div class="card">
            <h2>Full Configuration (YAML)</h2>
            <form method="POST" action="{save_url}">
                <div class="form-group">
                    <textarea name="config_yaml">{config_yaml}</textarea>
                </div>
                <button type="submit">Save Configuration</button>
                <button type="button" class="danger" onclick="{restart_js}">
                    Restart Server
                </button>
            </form>
        </div>
    </div>
    <script>{_JS_SCRIPT}</script>
</body>
</html>"""


_RESTART_CSS = """
body { font-family: sans-serif; text-align: center; padding: 50px; }
.spinner { animation: spin 1s linear infinite; font-size: 2em; }
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
"""


def _build_restart_html(redirect_url: str) -> str:
    """Build the restart page HTML."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Restarting...</title>
    <meta http-equiv="refresh" content="3;url={redirect_url}">
    <style>{_RESTART_CSS}</style>
</head>
<body>
    <div class="spinner">⟳</div>
    <h1>Restarting Server...</h1>
    <p>The server is restarting with the new configuration.</p>
    <p>You will be redirected automatically in a few seconds.</p>
</body>
</html>"""


def get_config_path() -> Path:
    """Get the config file path from environment or default."""
    config_env = os.environ.get("MCP_PROXY_CONFIG", "config.yaml")
    return Path(config_env)


def get_overrides_path(config_path: Path) -> Path:
    """Get the path for the overrides file (JSON next to YAML)."""
    return config_path.with_suffix(".overrides.json")


def load_raw_config(config_path: Path) -> dict[str, Any]:
    """Load the raw YAML config."""
    if not config_path.exists():
        return {"mcp_servers": {}, "tool_views": {}}
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return data


def load_overrides(config_path: Path) -> dict[str, Any]:
    """Load saved overrides."""
    overrides_path = get_overrides_path(config_path)
    if not overrides_path.exists():
        return {}
    with open(overrides_path) as f:
        return json.load(f)


def save_overrides(config_path: Path, overrides: dict[str, Any]) -> None:
    """Save overrides to JSON file."""
    overrides_path = get_overrides_path(config_path)
    with open(overrides_path, "w") as f:
        json.dump(overrides, f, indent=2)


def merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep merge overrides into base config."""
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def render_servers_html(servers: dict[str, Any]) -> str:
    """Render HTML for server list."""
    if not servers:
        return "<p>No servers configured.</p>"
    html_parts = []
    for name, cfg in servers.items():
        server_type = "HTTP" if cfg.get("url") else "stdio"
        if cfg.get("url"):
            details = cfg.get("url")
        else:
            cmd = cfg.get("command", "")
            args = " ".join(cfg.get("args", []))
            details = f"{cmd} {args}".strip()
        html_parts.append(
            f'<div class="server-item">'
            f"<h3>{name}</h3>"
            f"<p><strong>Type:</strong> {server_type}</p>"
            f"<p><strong>Details:</strong> <code>{details}</code></p>"
            f"</div>"
        )
    return "".join(html_parts)


def render_views_html(views: dict[str, Any]) -> str:
    """Render HTML for views list."""
    if not views:
        return "<p>No views configured.</p>"
    html_parts = []
    for name, cfg in views.items():
        desc = cfg.get("description", "No description")
        mode = cfg.get("exposure_mode", "direct")
        html_parts.append(
            f'<div class="view-item">'
            f"<h3>{name}</h3>"
            f"<p><strong>Description:</strong> {desc}</p>"
            f"<p><strong>Mode:</strong> {mode}</p>"
            f"</div>"
        )
    return "".join(html_parts)


def _get_session_secret() -> str:
    """Get the secret for signing session cookies.

    Uses the Auth0 client secret if available, otherwise generates one.
    """
    from mcp_proxy.auth import AUTH0_CLIENT_SECRET_VAR

    secret = os.environ.get(AUTH0_CLIENT_SECRET_VAR, "")
    if not secret:
        # Fall back to a generated secret (sessions won't survive restart)
        secret = secrets.token_hex(32)
    return secret


def _sign_session_data(data: str) -> str:
    """Sign session data with HMAC-SHA256."""
    secret = _get_session_secret()
    signature = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{signature}"


def _verify_session_data(signed_data: str) -> str | None:
    """Verify signed session data. Returns the data if valid, None otherwise."""
    if "." not in signed_data:
        return None
    data, signature = signed_data.rsplit(".", 1)
    expected = _sign_session_data(data).rsplit(".", 1)[1]
    if hmac.compare_digest(signature, expected):
        return data
    return None


def create_session_cookie(user_id: str) -> str:
    """Create a signed session cookie value."""
    expires = int(time.time()) + SESSION_MAX_AGE
    data = json.dumps({"user_id": user_id, "expires": expires})
    return _sign_session_data(data)


def verify_session_cookie(cookie_value: str) -> dict[str, Any] | None:
    """Verify a session cookie. Returns session data if valid, None otherwise."""
    data = _verify_session_data(cookie_value)
    if not data:
        return None
    try:
        session = json.loads(data)
        if session.get("expires", 0) < time.time():
            return None  # Expired
        return session
    except (json.JSONDecodeError, KeyError):
        return None


def is_browser_request(request: Request) -> bool:
    """Check if request appears to be from a browser (vs API client)."""
    accept = request.headers.get("Accept", "")
    return "text/html" in accept


def get_authorization_url(auth_provider: "AuthProvider | None") -> str | None:
    """Get the OAuth authorization URL from the auth provider."""
    if auth_provider is None:
        return None

    # For OIDCProxy and CompositeAuthProvider, get the upstream auth URL
    # The OIDCProxy uses the OIDC config_url to discover the auth endpoint
    if hasattr(auth_provider, "oidc_provider"):
        auth_provider = auth_provider.oidc_provider
    if auth_provider is None:
        return None

    # Get the base URL and construct the authorize endpoint
    if hasattr(auth_provider, "base_url"):
        base = str(auth_provider.base_url).rstrip("/")
        return f"{base}/authorize"
    return None


def _get_oidc_provider(
    auth_provider: "AuthProvider | None",
) -> "AuthProvider | None":
    """Get the OIDC provider from a potentially composite auth provider."""
    if auth_provider is None:
        return None
    if hasattr(auth_provider, "oidc_provider"):
        return auth_provider.oidc_provider
    return auth_provider


def _get_oauth_client_id(auth_provider: "AuthProvider | None") -> str:
    """Get the OAuth client ID from the auth provider."""
    from mcp_proxy.auth import AUTH0_CLIENT_ID_VAR

    provider = _get_oidc_provider(auth_provider)
    if provider and hasattr(provider, "client_id"):
        return str(provider.client_id)
    return os.environ.get(AUTH0_CLIENT_ID_VAR, "")


def _get_token_url(auth_provider: "AuthProvider | None") -> str | None:
    """Get the OAuth token endpoint URL from the auth provider."""
    provider = _get_oidc_provider(auth_provider)
    if provider is None:
        return None

    # Try to get the token endpoint from the OIDC provider
    if hasattr(provider, "upstream_token_endpoint"):
        return str(provider.upstream_token_endpoint)

    # Fall back to constructing from base_url
    if hasattr(provider, "base_url"):
        base = str(provider.base_url).rstrip("/")
        return f"{base}/oauth/token"
    return None


async def _exchange_code_for_token(
    auth_provider: "AuthProvider | None",
    code: str,
    redirect_uri: str,
) -> dict[str, Any] | None:
    """Exchange an authorization code for an access token."""
    import httpx

    from mcp_proxy.auth import AUTH0_CLIENT_ID_VAR, AUTH0_CLIENT_SECRET_VAR

    token_url = _get_token_url(auth_provider)
    if not token_url:
        return None

    provider = _get_oidc_provider(auth_provider)
    client_id = (
        str(provider.client_id)
        if provider and hasattr(provider, "client_id")
        else os.environ.get(AUTH0_CLIENT_ID_VAR, "")
    )
    client_secret = (
        str(provider.client_secret)
        if provider and hasattr(provider, "client_secret")
        else os.environ.get(AUTH0_CLIENT_SECRET_VAR, "")
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return None


def create_web_ui_routes(
    path_prefix: str = "/config",
    check_auth: AuthChecker | None = None,
    auth_provider: "AuthProvider | None" = None,
) -> list[Route]:
    """Create web UI routes for config editing.

    Args:
        path_prefix: URL prefix for config routes
        check_auth: Optional async function to check auth, returns JSONResponse on error
        auth_provider: Optional auth provider for OAuth redirect (for browsers)

    Returns:
        List of Starlette routes
    """

    async def check_browser_auth(request: Request) -> Response | None:
        """Check auth for browser requests. Returns redirect or error if not authed."""
        # Check for valid session cookie first
        session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if session_cookie:
            session = verify_session_cookie(session_cookie)
            if session:
                return None  # Authenticated via session

        # Check for Bearer token (for API access)
        if check_auth:
            auth_error = await check_auth(request)
            if auth_error is None:
                return None  # Authenticated via token

        # Not authenticated - for browsers, redirect to OAuth login
        if is_browser_request(request):
            auth_url = get_authorization_url(auth_provider)
            if auth_url:
                # Store the original URL to redirect back to after login
                return_url = str(request.url)
                encoded_url = urllib.parse.quote(return_url)
                login_url = f"{path_prefix}/login?return_url={encoded_url}"
                return RedirectResponse(login_url, status_code=302)
            # No auth provider available - show error
            return HTMLResponse(
                "<h1>Authentication Required</h1>"
                "<p>OAuth is not configured. "
                "Please set up OIDC environment variables.</p>",
                status_code=401,
            )

        # API request without valid token
        if check_auth:
            return await check_auth(request)
        return None

    async def config_ui(request: Request) -> Response:
        """Render the config editor UI."""
        auth_result = await check_browser_auth(request)
        if auth_result:
            return auth_result

        config_path = get_config_path()
        raw_config = load_raw_config(config_path)
        overrides = load_overrides(config_path)
        merged = merge_config(raw_config, overrides)

        alert = ""
        if "saved" in request.query_params:
            alert = (
                '<div class="alert alert-success">'
                "Configuration saved successfully!</div>"
            )
        elif "error" in request.query_params:
            err_msg = request.query_params.get("error", "Unknown error")
            alert = f'<div class="alert alert-error">Error: {err_msg}</div>'

        html = _build_html_template(
            alert=alert,
            servers_html=render_servers_html(merged.get("mcp_servers", {})),
            views_html=render_views_html(merged.get("tool_views", {})),
            config_yaml=yaml.dump(merged, default_flow_style=False, sort_keys=False),
            save_url=f"{path_prefix}/save",
            restart_url=f"{path_prefix}/restart",
        )
        return HTMLResponse(html)

    async def save_config(request: Request) -> Response:
        """Save the configuration."""
        auth_result = await check_browser_auth(request)
        if auth_result:
            return auth_result

        form = await request.form()
        config_yaml = form.get("config_yaml", "")

        try:
            # Parse and validate YAML
            new_config = yaml.safe_load(config_yaml)
            if not isinstance(new_config, dict):
                raise ValueError("Invalid configuration format")

            # Save as overrides (preserves original file)
            config_path = get_config_path()
            save_overrides(config_path, new_config)

            return RedirectResponse(f"{path_prefix}?saved=1", status_code=303)
        except Exception as e:
            return RedirectResponse(f"{path_prefix}?error={e}", status_code=303)

    async def restart_server(request: Request) -> Response:
        """Trigger server restart."""
        auth_result = await check_browser_auth(request)
        if auth_result:
            return auth_result

        # Check if API call (Accept: application/json) or browser
        is_api = "application/json" in request.headers.get("Accept", "")

        # Write restart marker file for process managers to detect
        config_path = get_config_path()
        restart_marker = config_path.parent / ".mcp-proxy-restart"
        try:
            restart_marker.write_text("restart")
        except Exception:
            pass  # Not critical if this fails

        # Send SIGHUP to self to trigger reload (common pattern)
        # The actual restart logic will be handled by the parent process
        try:
            os.kill(os.getpid(), signal.SIGHUP)
            if is_api:
                return JSONResponse({"status": "restart_initiated"})
            else:
                return HTMLResponse(_build_restart_html(path_prefix))
        except Exception as e:
            if is_api:
                return JSONResponse({"error": str(e)}, status_code=500)
            else:
                return RedirectResponse(
                    f"{path_prefix}?error=Restart+failed:+{e}", status_code=303
                )

    async def get_config_json(request: Request) -> Response:
        """Get current config as JSON (API endpoint)."""
        auth_result = await check_browser_auth(request)
        if auth_result:
            return auth_result

        config_path = get_config_path()
        raw_config = load_raw_config(config_path)
        overrides = load_overrides(config_path)
        merged = merge_config(raw_config, overrides)
        return JSONResponse(merged)

    async def update_config_json(request: Request) -> Response:
        """Update config via JSON API."""
        auth_result = await check_browser_auth(request)
        if auth_result:
            return auth_result

        try:
            body = await request.json()
            config_path = get_config_path()
            save_overrides(config_path, body)
            return JSONResponse({"status": "saved"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def login_page(request: Request) -> Response:
        """Handle login - redirect to OAuth provider."""
        return_url = request.query_params.get("return_url", path_prefix)
        auth_url = get_authorization_url(auth_provider)

        if not auth_url:
            return HTMLResponse(
                "<h1>OAuth Not Configured</h1>"
                "<p>Please configure OIDC environment variables to enable login.</p>",
                status_code=500,
            )

        # Build auth URL with state containing the return URL
        # The OIDCProxy/OAuthProxy will handle the actual OAuth flow
        state = urllib.parse.quote(return_url)
        # Include callback URL to our callback endpoint
        callback_url = str(request.url_for("config_login_callback"))
        full_auth_url = (
            f"{auth_url}?"
            f"response_type=code&"
            f"client_id={_get_oauth_client_id(auth_provider)}&"
            f"redirect_uri={urllib.parse.quote(callback_url)}&"
            f"state={state}"
        )
        return RedirectResponse(full_auth_url, status_code=302)

    async def login_callback(request: Request) -> Response:
        """Handle OAuth callback - exchange code for token and set session."""
        code = request.query_params.get("code")
        state = request.query_params.get("state", path_prefix)
        return_url = urllib.parse.unquote(state)

        if not code:
            error = request.query_params.get("error", "Unknown error")
            return HTMLResponse(
                f"<h1>Login Failed</h1><p>Error: {error}</p>",
                status_code=400,
            )

        # Exchange code for token
        token_url = _get_token_url(auth_provider)
        if not token_url:
            return HTMLResponse(
                "<h1>OAuth Not Configured</h1>",
                status_code=500,
            )

        # Exchange the authorization code for an access token
        callback_url = str(request.url_for("config_login_callback"))
        token_response = await _exchange_code_for_token(
            auth_provider, code, callback_url
        )
        if not token_response:
            return HTMLResponse(
                "<h1>Token Exchange Failed</h1>"
                "<p>Could not exchange authorization code for token.</p>",
                status_code=500,
            )

        # Create session cookie with user info from token
        user_id = token_response.get("sub", token_response.get("email", "user"))
        session_value = create_session_cookie(user_id)

        response = RedirectResponse(return_url, status_code=302)
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
        response = RedirectResponse(path_prefix, status_code=302)
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

    return [
        Route(path_prefix, config_ui, methods=["GET"]),
        Route(f"{path_prefix}/save", save_config, methods=["POST"]),
        Route(f"{path_prefix}/restart", restart_server, methods=["GET", "POST"]),
        Route(f"{path_prefix}/api", get_config_json, methods=["GET"]),
        Route(f"{path_prefix}/api", update_config_json, methods=["PUT"]),
        Route(f"{path_prefix}/login", login_page, methods=["GET"]),
        Route(
            f"{path_prefix}/login/callback",
            login_callback,
            methods=["GET"],
            name="config_login_callback",
        ),
        Route(f"{path_prefix}/logout", logout, methods=["GET", "POST"]),
    ]
