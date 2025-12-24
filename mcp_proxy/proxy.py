"""Main MCP Proxy class."""

import os
import re
from typing import Any, Callable

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
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
from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.views import ToolView


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} environment variable references in a string."""
    pattern = r'\$\{([^}]+)\}'

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(pattern, replacer, value)


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
        self.upstream_clients: dict[str, Client] = {}
        self._upstream_tools: dict[str, list[Any]] = {}  # Cached tools from upstreams
        self._initialized = False

        # Create views from config
        for view_name, view_config in config.tool_views.items():
            self.views[view_name] = ToolView(name=view_name, config=view_config)

        # Register stub tools on the default server (for stdio transport)
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(self.server, default_tools)

    async def _create_client(self, server_name: str) -> Client:
        """Create an MCP client for an upstream server.

        Args:
            server_name: Name of the server from config

        Returns:
            FastMCP Client instance configured for the server
        """
        if server_name not in self.config.mcp_servers:
            raise ValueError(f"Server '{server_name}' not found in config")

        server_config = self.config.mcp_servers[server_name]
        return self._create_client_from_config(server_config)

    def _create_client_from_config(self, config: UpstreamServerConfig) -> Client:
        """Create an MCP client from server configuration."""
        if config.url:
            # HTTP-based server
            url = expand_env_vars(config.url)
            headers = {k: expand_env_vars(v) for k, v in config.headers.items()}
            transport = StreamableHttpTransport(url=url, headers=headers)
            return Client(transport=transport)
        elif config.command:
            # Stdio-based server (command execution)
            command = config.command
            args = config.args or []
            env = {k: expand_env_vars(v) for k, v in config.env.items()} if config.env else None
            transport = StdioTransport(command=command, args=args, env=env)
            return Client(transport=transport)
        else:
            raise ValueError("Server config must have either 'url' or 'command'")

    async def initialize(self) -> None:
        """Initialize upstream connections.

        Creates MCP clients for all configured servers and fetches
        their tool lists.
        """
        if self._initialized:
            return

        for server_name in self.config.mcp_servers:
            client = await self._create_client(server_name)
            self.upstream_clients[server_name] = client

        # Initialize views with upstream clients
        for view in self.views.values():
            await view.initialize(self.upstream_clients)

        self._initialized = True

    async def fetch_upstream_tools(self, server_name: str) -> list[Any]:
        """Fetch tools from an upstream server.

        Args:
            server_name: Name of the server to fetch tools from

        Returns:
            List of tool objects from the upstream server
        """
        if server_name not in self.upstream_clients:
            raise ValueError(f"No client for server '{server_name}'")

        client = self.upstream_clients[server_name]
        async with client:
            tools = await client.list_tools()
            self._upstream_tools[server_name] = tools
            return tools

    async def call_upstream_tool(
        self, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        """Call a tool on an upstream server.

        Args:
            server_name: Name of the upstream server
            tool_name: Name of the tool to call
            args: Arguments to pass to the tool

        Returns:
            Result from the upstream tool
        """
        if server_name not in self.upstream_clients:
            raise ValueError(f"No client for server '{server_name}'")

        client = self.upstream_clients[server_name]
        async with client:
            return await client.call_tool(tool_name, args)

    async def refresh_upstream_tools(self) -> None:
        """Refresh tool lists from all upstream servers."""
        for server_name in self.upstream_clients:
            await self.fetch_upstream_tools(server_name)

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

        # Handle include_all: include all tools from all servers
        if view_config.include_all:
            for server_name, server_config in self.config.mcp_servers.items():
                if server_config.tools:
                    for tool_name, tool_config in server_config.tools.items():
                        # Check if view has override for this tool
                        view_override = None
                        if server_name in view_config.tools:
                            view_override = view_config.tools[server_name].get(tool_name)

                        if view_override:
                            # Use view's override
                            exposed_name = view_override.name or tool_name
                            description = view_override.description or tool_config.description or ""
                        else:
                            exposed_name = tool_name
                            description = tool_config.description or ""

                        tools.append(ToolInfo(
                            name=exposed_name,
                            description=description,
                            server=server_name
                        ))
        else:
            # Only include explicitly listed tools
            for server_name, server_tools in view_config.tools.items():
                for tool_name, tool_config in server_tools.items():
                    # Apply name override if specified
                    exposed_name = tool_config.name if tool_config.name else tool_name
                    description = tool_config.description or ""
                    tools.append(ToolInfo(
                        name=exposed_name,
                        description=description,
                        server=server_name
                    ))

        # Add composite tools
        for comp_name, comp_tool in view.composite_tools.items():
            tools.append(ToolInfo(
                name=comp_name,
                description=comp_tool.description,
                server=""  # Composite tools don't have a single server
            ))

        # Add custom tools
        for custom_name, custom_fn in view.custom_tools.items():
            description = getattr(custom_fn, "_tool_description", "")
            tools.append(ToolInfo(
                name=custom_name,
                description=description,
                server=""  # Custom tools don't have an upstream server
            ))

        return tools

    def get_view_mcp(self, view_name: str) -> FastMCP:
        """Get a FastMCP instance for a specific view.

        Args:
            view_name: Name of the view

        Returns:
            FastMCP instance with the view's tools registered
        """
        if view_name not in self.views:
            raise ValueError(f"View '{view_name}' not found")

        view = self.views[view_name]
        view_config = view.config
        mcp = FastMCP(f"MCP Proxy - {view_name}")

        if view_config.exposure_mode == "search":
            # In search mode, only register the search meta-tool
            self._register_search_tool(mcp, view_name)
        else:
            # Direct mode: register all view tools with view for callable routing
            view_tools = self.get_view_tools(view_name)
            self._register_tools_on_mcp(mcp, view_tools, view=view)

        return mcp

    def _register_search_tool(self, mcp: FastMCP, view_name: str) -> None:
        """Register the search meta-tool for a view."""
        from mcp_proxy.search import ToolSearcher

        view_tools = self.get_view_tools(view_name)
        tools_data = [
            {"name": t.name, "description": t.description}
            for t in view_tools
        ]
        searcher = ToolSearcher(view_name=view_name, tools=tools_data)
        search_tool = searcher.create_search_tool()

        # Register the search tool on the FastMCP
        search_name = f"{view_name}_search_tools"

        async def search_tools_wrapper(query: str = "", limit: int = 10) -> dict:
            return await search_tool(query=query, limit=limit)

        search_tools_wrapper.__name__ = search_name
        search_tools_wrapper.__doc__ = f"Search for tools in the {view_name} view"

        mcp.tool(name=search_name, description=f"Search for tools in the {view_name} view")(
            search_tools_wrapper
        )

    def _register_tools_on_mcp(
        self, mcp: FastMCP, tools: list[ToolInfo], view: ToolView | None = None
    ) -> None:
        """Register tools on a FastMCP instance.

        If a view is provided, registers callable tools that route through the view.
        Otherwise, registers stub tools.
        """
        for tool_info in tools:
            # Capture tool_info in closure
            _tool_name = tool_info.name
            _tool_server = tool_info.server
            _tool_desc = tool_info.description or f"Tool: {_tool_name}"

            if view and _tool_name in view.custom_tools:
                # Register actual custom tool
                custom_fn = view.custom_tools[_tool_name]
                mcp.tool(name=_tool_name, description=_tool_desc)(custom_fn)
            elif view and _tool_name in view.composite_tools:
                # Register composite tool wrapper
                # FastMCP doesn't support **kwargs, so we register with view.call_tool
                parallel_tool = view.composite_tools[_tool_name]

                # Get input schema from the parallel tool
                input_schema = parallel_tool.input_schema

                # Create wrapper with explicit args based on schema
                def make_composite_wrapper(
                    v: ToolView, name: str, schema: dict
                ) -> Callable[..., Any]:
                    # Since FastMCP doesn't support **kwargs, create a wrapper
                    # that takes no args and relies on the MCP layer to pass JSON
                    async def composite_wrapper() -> Any:
                        # Called with no explicit args - MCP handles JSON payload
                        return {"message": f"Composite tool {name} - call via view.call_tool"}

                    return composite_wrapper

                wrapper = make_composite_wrapper(view, _tool_name, input_schema)
                wrapper.__name__ = _tool_name
                wrapper.__doc__ = _tool_desc
                mcp.tool(name=_tool_name, description=_tool_desc)(wrapper)
            else:
                # Create a stub function - use default args to capture values
                def make_stub(name: str, server: str) -> Callable[[], str]:
                    async def tool_stub() -> str:
                        """Stub tool - actual execution routes through proxy."""
                        return f"Tool '{name}' from server '{server}' - use upstream connection"

                    return tool_stub

                stub = make_stub(_tool_name, _tool_server)
                stub.__name__ = _tool_name
                stub.__doc__ = _tool_desc
                mcp.tool(name=_tool_name, description=_tool_desc)(stub)

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

            # For search mode, return the search tool instead of underlying tools
            if view.config.exposure_mode == "search":
                tools_list = [{"name": f"{view_name}_search_tools"}]
            else:
                tools = self.get_view_tools(view_name)
                tools_list = [{"name": t.name} for t in tools] if tools else []

            return JSONResponse({
                "name": view_name,
                "description": view.config.description,
                "exposure_mode": view.config.exposure_mode,
                "tools": tools_list
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
