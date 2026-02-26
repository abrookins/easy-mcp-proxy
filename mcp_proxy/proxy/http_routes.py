"""HTTP route handlers for MCP Proxy.

This module provides route handler functions for the proxy's HTTP API,
including health checks, view info, and view listing endpoints.
"""

from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from .proxy import MCPProxy


async def check_auth_token(
    request: Request, auth_provider: Any | None
) -> JSONResponse | None:
    """Check authentication if auth is configured.

    Args:
        request: The incoming HTTP request
        auth_provider: The auth provider (OIDCProxy) or None if auth is not configured

    Returns:
        None if auth passes, or a 401 JSONResponse if auth fails.
    """
    if auth_provider is None:
        return None  # No auth configured, allow access

    # Extract bearer token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            {
                "error": "invalid_token",
                "error_description": "Missing or invalid Authorization header",
            },
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]  # Remove "Bearer " prefix
    if not token:
        return JSONResponse(
            {
                "error": "invalid_token",
                "error_description": "Empty bearer token",
            },
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate token using the auth provider
    access_token = await auth_provider.verify_token(token)
    if access_token is None:
        return JSONResponse(
            {
                "error": "invalid_token",
                "error_description": "Invalid or expired token",
            },
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return None  # Auth passed


def create_health_check_handler():
    """Create health check route handler."""

    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    return health_check


def create_view_info_handler(proxy: "MCPProxy", auth_provider: Any | None):
    """Create view info route handler."""

    async def view_info(request: Request) -> JSONResponse:
        # Check authentication first
        auth_error = await check_auth_token(request, auth_provider)
        if auth_error:
            return auth_error

        view_name = request.path_params["view_name"]
        if view_name not in proxy.views:
            return JSONResponse(
                {"error": f"View '{view_name}' not found"}, status_code=404
            )
        view = proxy.views[view_name]

        if view.config.exposure_mode == "search":
            tools_list = [{"name": f"{view_name}_search_tools"}]
        elif view.config.exposure_mode == "search_per_server":
            # List search tools for each server
            tools = proxy.get_view_tools(view_name)
            servers = set(t.server or "custom" for t in tools)
            tools_list = [{"name": f"{s}_search_tools"} for s in sorted(servers)]
        else:
            tools = proxy.get_view_tools(view_name)
            tools_list = [{"name": t.name} for t in tools] if tools else []

        return JSONResponse(
            {
                "name": view_name,
                "description": view.config.description,
                "exposure_mode": view.config.exposure_mode,
                "tools": tools_list,
            }
        )

    return view_info


def create_list_views_handler(proxy: "MCPProxy", auth_provider: Any | None):
    """Create list views route handler."""

    async def list_views(request: Request) -> JSONResponse:
        # Check authentication first
        auth_error = await check_auth_token(request, auth_provider)
        if auth_error:
            return auth_error

        views_info = {
            name: {
                "description": view.config.description,
                "exposure_mode": view.config.exposure_mode,
            }
            for name, view in proxy.views.items()
        }
        return JSONResponse({"views": views_info})

    return list_views
