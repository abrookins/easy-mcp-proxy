"""Main MCP Proxy class."""

from typing import Any, Callable

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_proxy.hooks import (
    HookResult,
    ToolCallContext,
    execute_post_call,
    execute_pre_call,
)
from mcp_proxy.models import ProxyConfig
from mcp_proxy.views import ToolView


class ToolInfo:
    """Simple class to hold tool information."""

    def __init__(self, name: str, description: str = "", server: str = ""):
        self.name = name
        self.description = description
        self.server = server

    def __repr__(self) -> str:
        return f"ToolInfo(name={self.name!r}, server={self.server!r})"


class MCPProxy:
    """MCP Proxy that aggregates and filters tools from upstream servers."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self.views: dict[str, ToolView] = {}
        self.server = FastMCP("MCP Tool View Proxy")

        # Create views from config
        for view_name, view_config in config.tool_views.items():
            self.views[view_name] = ToolView(name=view_name, config=view_config)

        # Register stub tools on the default server (for stdio transport)
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(self.server, default_tools)

    def _wrap_tool_with_hooks(
        self,
        tool: Callable,
        pre_hook: Callable | None,
        post_hook: Callable | None,
        view_name: str,
        tool_name: str,
        upstream_server: str,
    ) -> Callable:
        """Wrap a tool with pre/post hook execution."""

        async def wrapped(**kwargs) -> Any:
            context = ToolCallContext(
                view_name=view_name,
                tool_name=tool_name,
                upstream_server=upstream_server,
            )
            args = kwargs

            # Pre-hook
            if pre_hook:
                hook_result = await execute_pre_call(pre_hook, args, context)
                if hook_result.args:
                    args = hook_result.args

            # Call original tool
            result = await tool(**args)

            # Post-hook
            if post_hook:
                hook_result = await execute_post_call(post_hook, result, args, context)
                if hook_result.result is not None:
                    result = hook_result.result

            return result

        return wrapped

    def run(self, transport: str = "stdio", port: int | None = None) -> None:  # pragma: no cover
        """Run the proxy server."""
        if transport == "stdio":
            self.server.run(transport="stdio")
        else:
            # For HTTP transport, use http_app() which has tools registered
            import uvicorn

            app = self.http_app()
            uvicorn.run(app, host="0.0.0.0", port=port or 8000)

    def get_view_tools(self, view_name: str | None) -> list["ToolInfo"]:
        """Get the list of tools for a specific view.

        Args:
            view_name: Name of the view, or None for default (all mcp_servers tools)

        Returns:
            List of ToolInfo objects with name and description attributes
        """
        tools: list[ToolInfo] = []

        if view_name is None:
            # Default view: return all tools from mcp_servers
            for server_name, server_config in self.config.mcp_servers.items():
                if server_config.tools:
                    for tool_name, tool_config in server_config.tools.items():
                        description = tool_config.description or ""
                        tools.append(ToolInfo(
                            name=tool_name,
                            description=description,
                            server=server_name
                        ))
            return tools

        if view_name not in self.views:
            raise ValueError(f"View '{view_name}' not found")

        # Return tools from the specific view
        view = self.views[view_name]
        view_config = view.config

        for server_name, server_tools in view_config.tools.items():
            for tool_name, tool_config in server_tools.items():
                # Get description from view config, or fall back to empty
                description = tool_config.description or ""
                tools.append(ToolInfo(
                    name=tool_name,
                    description=description,
                    server=server_name
                ))

        return tools

    def _register_tools_on_mcp(
        self, mcp: FastMCP, tools: list[ToolInfo]
    ) -> None:
        """Register tool stubs on a FastMCP instance.

        These are placeholder tools that expose the tool names and descriptions
        to MCP clients. Actual tool execution routes through upstream servers.
        """
        for tool_info in tools:
            # Capture tool_info in closure
            _tool_name = tool_info.name
            _tool_server = tool_info.server
            _tool_desc = tool_info.description or f"Tool: {_tool_name}"

            # Create a stub function for each tool (no **kwargs - FastMCP doesn't support it)
            async def tool_stub() -> str:
                """Stub tool - actual execution routes through proxy."""
                return f"Tool '{_tool_name}' from server '{_tool_server}' - use upstream connection"

            # Set metadata for the tool
            tool_stub.__name__ = _tool_name
            tool_stub.__doc__ = _tool_desc

            # Register with FastMCP
            mcp.tool(name=_tool_name, description=_tool_desc)(tool_stub)

    def http_app(
        self,
        path: str = "",
        view_prefix: str = "/view",
    ) -> Starlette:
        """Create an ASGI app with multi-view routing.

        Args:
            path: Base path prefix for all endpoints
            view_prefix: Path prefix for view-specific endpoints

        Returns:
            Starlette ASGI application with routes:
            - {path}/mcp - Default MCP endpoint (all mcp_servers tools)
            - {path}{view_prefix}/{name}/mcp - View-specific MCP endpoint
            - {path}/views - List all available views
            - {path}/views/{name} - Get view info
            - {path}/health - Health check endpoint
        """
        from contextlib import asynccontextmanager

        # Create FastMCP instances for default and each view
        default_mcp = FastMCP("MCP Proxy - Default")

        # Register tools from all mcp_servers on default MCP
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(default_mcp, default_tools)

        view_mcps: dict[str, FastMCP] = {}
        for view_name in self.views:
            view_mcp = FastMCP(f"MCP Proxy - {view_name}")
            # Register view-specific tools
            view_tools = self.get_view_tools(view_name)
            self._register_tools_on_mcp(view_mcp, view_tools)
            view_mcps[view_name] = view_mcp

        # Get MCP HTTP apps
        default_mcp_app = default_mcp.http_app(path="/mcp")

        view_mcp_apps: dict[str, Any] = {}
        for view_name, view_mcp in view_mcps.items():
            view_mcp_apps[view_name] = view_mcp.http_app(path="/mcp")

        # Create combined lifespan that handles all MCP apps
        @asynccontextmanager
        async def combined_lifespan(app: Starlette):  # pragma: no cover
            # Use the default MCP app's lifespan for session management
            async with default_mcp_app.lifespan(default_mcp_app):
                yield

        # Build routes - order matters: more specific routes first
        routes: list[Route | Mount] = []

        # Health check endpoint
        async def health_check(request: Request) -> JSONResponse:
            return JSONResponse({"status": "healthy"})

        routes.append(Route(f"{path}/health", health_check, methods=["GET"]))

        # View info endpoint (before /views to avoid conflict)
        async def view_info(request: Request) -> JSONResponse:
            view_name = request.path_params["view_name"]
            if view_name not in self.views:
                return JSONResponse(
                    {"error": f"View '{view_name}' not found"},
                    status_code=404
                )
            view = self.views[view_name]
            tools = self.get_view_tools(view_name)
            return JSONResponse({
                "name": view_name,
                "description": view.config.description,
                "exposure_mode": view.config.exposure_mode,
                "tools": [{"name": t.name} for t in tools] if tools else []
            })

        routes.append(
            Route(f"{path}/views/{{view_name}}", view_info, methods=["GET"])
        )

        # List views endpoint
        async def list_views(request: Request) -> JSONResponse:
            views_info = {
                name: {
                    "description": view.config.description,
                    "exposure_mode": view.config.exposure_mode,
                }
                for name, view in self.views.items()
            }
            return JSONResponse({"views": views_info})

        routes.append(Route(f"{path}/views", list_views, methods=["GET"]))

        # Mount view-specific MCP apps BEFORE default (more specific first)
        for view_name, view_mcp_app in view_mcp_apps.items():
            routes.append(
                Mount(f"{path}{view_prefix}/{view_name}", app=view_mcp_app)
            )

        # Mount default MCP app last (catches remaining /mcp requests)
        if path:
            routes.append(Mount(path, app=default_mcp_app))
        else:
            routes.append(Mount("/", app=default_mcp_app))

        # Create the Starlette app with proper lifespan management
        app = Starlette(routes=routes, lifespan=combined_lifespan)

        return app
