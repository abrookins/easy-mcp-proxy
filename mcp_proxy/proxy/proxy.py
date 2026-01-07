"""Main MCP Proxy class."""

from contextlib import asynccontextmanager
from typing import Any, Callable

from fastmcp import Client, FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_proxy.hooks import ToolCallContext, execute_post_call, execute_pre_call
from mcp_proxy.models import ProxyConfig
from mcp_proxy.views import ToolView

from .client import ClientManager
from .schema import create_tool_with_schema, transform_args
from .tool_info import ToolInfo
from .tools import (
    _process_server_all_tools,
    _process_server_with_tools_config,
    _process_view_explicit_tools,
    _process_view_include_all_fallback,
    _process_view_include_all_with_upstream,
)


class MCPProxy:
    """MCP Proxy that aggregates and filters tools from upstream servers."""

    def __init__(self, config: ProxyConfig):
        """Initialize the MCP Proxy with the given configuration.

        Args:
            config: Proxy configuration containing server and view definitions.
        """
        self.config = config
        self.views: dict[str, ToolView] = {}
        self._client_manager = ClientManager(config)
        self._initialized = False
        self.upstream_instructions: dict[str, str] = {}

        self.server = FastMCP("MCP Tool View Proxy")

        # Create views from config
        for view_name, view_config in config.tool_views.items():
            self.views[view_name] = ToolView(name=view_name, config=view_config)

        # Register stub tools on the default server (for stdio transport)
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(self.server, default_tools)

    # Delegate client management to ClientManager
    @property
    def upstream_clients(self) -> dict[str, Client]:
        """Map of server names to their MCP clients."""
        return self._client_manager.upstream_clients

    @upstream_clients.setter
    def upstream_clients(self, value: dict[str, Client]) -> None:
        """Set the map of server names to clients."""
        self._client_manager.upstream_clients = value

    @property
    def _upstream_tools(self) -> dict[str, list[Any]]:
        """Cached tools fetched from upstream servers."""
        return self._client_manager._upstream_tools

    @_upstream_tools.setter
    def _upstream_tools(self, value: dict[str, list[Any]]) -> None:
        """Set the cached upstream tools."""
        self._client_manager._upstream_tools = value

    @property
    def _active_clients(self) -> dict[str, Client]:
        """Map of server names to active (connected) clients."""
        return self._client_manager._active_clients

    @_active_clients.setter
    def _active_clients(self, value: dict[str, Client]) -> None:
        """Set the active clients map."""
        self._client_manager._active_clients = value

    def _create_client_from_config(self, config):
        """Create an MCP client from server configuration."""
        return self._client_manager.create_client_from_config(config)

    async def _create_client(self, server_name: str) -> Client:
        """Create and connect a new client for the specified server."""
        return await self._client_manager.create_client(server_name)

    async def fetch_upstream_tools(self, server_name: str) -> list[Any]:
        """Fetch tools and instructions from an upstream server."""
        if server_name not in self.upstream_clients:
            raise ValueError(f"No client for server '{server_name}'")

        client = self.upstream_clients[server_name]
        async with client:
            # Fetch instructions while client is connected
            await self.fetch_upstream_instructions(server_name, client)
            # Fetch tools
            tools = await client.list_tools()
            self._upstream_tools[server_name] = tools
            return tools

    async def refresh_upstream_tools(self) -> None:
        """Refresh tools and instructions from all upstream servers."""
        for server_name in self.upstream_clients:
            try:
                await self.fetch_upstream_tools(server_name)
            except Exception:
                # Log error but continue - tool will work without schema
                pass

    async def connect_clients(self, fetch_tools: bool = False) -> None:
        """Establish persistent connections to all upstream servers.

        Args:
            fetch_tools: If True, also fetch tool metadata after connecting.
        """
        return await self._client_manager.connect_clients(fetch_tools=fetch_tools)

    async def disconnect_clients(self) -> None:
        """Disconnect from all upstream servers and clean up resources."""
        return await self._client_manager.disconnect_clients()

    async def fetch_tools_from_active_clients(self) -> None:
        """Fetch tool metadata and instructions from all active (connected) clients."""
        await self._client_manager.refresh_tools_from_active_clients(
            instruction_callback=self.fetch_upstream_instructions
        )

    def get_active_client(self, server_name: str) -> Client | None:
        """Get the active client for a server, or None if not connected."""
        return self._client_manager.get_active_client(server_name)

    def has_active_connection(self, server_name: str) -> bool:
        """Check if there's an active connection to the specified server."""
        return self._client_manager.has_active_connection(server_name)

    async def reconnect_client(self, server_name: str) -> None:
        """Attempt to reconnect a failed upstream client."""
        await self._client_manager._reconnect_client(server_name)

    async def call_upstream_tool(
        self, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        """Call a tool on an upstream server.

        Args:
            server_name: Name of the upstream server.
            tool_name: Name of the tool to call.
            args: Arguments to pass to the tool.

        Returns:
            The result from the upstream tool.
        """
        return await self._client_manager.call_upstream_tool(
            server_name, tool_name, args
        )

    def get_aggregated_instructions(self) -> str | None:
        """Get aggregated instructions from all upstream servers.

        Returns a combined string with instructions from each server,
        or None if no instructions are available.
        """
        if not self.upstream_instructions:
            return None

        parts = []
        for server_name, instructions in self.upstream_instructions.items():
            if instructions:
                parts.append(f"## {server_name}\n\n{instructions}")

        if not parts:
            return None

        return "\n\n".join(parts)

    async def fetch_upstream_instructions(
        self, server_name: str, client: Client
    ) -> None:
        """Fetch and store instructions from an upstream server.

        Args:
            server_name: Name of the server
            client: Connected client to fetch instructions from
        """
        init_result = client.initialize_result
        if init_result and init_result.instructions:
            self.upstream_instructions[server_name] = init_result.instructions

    def _create_lifespan(self) -> Callable:
        """Create a lifespan context manager that initializes upstream connections."""

        @asynccontextmanager
        async def proxy_lifespan(mcp: FastMCP):
            """Initialize upstream connections on server startup."""
            # Connect to upstream servers (spawns processes, keeps connections alive)
            await self.connect_clients(fetch_tools=True)

            # Initialize views with active clients
            for view_name, view in self.views.items():
                await view.initialize(
                    self.upstream_clients,
                    get_client=self.get_active_client,
                    reconnect_client=self.reconnect_client,
                )
                view_tools = self.get_view_tools(view_name)
                view.update_tool_mapping(view_tools)

            self._initialized = True
            try:
                yield
            finally:
                await self.disconnect_clients()

        return proxy_lifespan

    def sync_fetch_tools(self) -> None:
        """Synchronously fetch tools from all upstream servers.

        This fetches tool metadata (names, descriptions, schemas) from upstream
        servers so they can be registered before the proxy starts. The actual
        persistent connections for tool execution are established later by
        connect_clients() during the server lifespan.
        """
        import asyncio

        # Skip if tools are already fetched
        if self._upstream_tools:
            return

        async def _fetch_all():
            for server_name in self.config.mcp_servers:
                try:
                    if server_name not in self.upstream_clients:
                        client = await self._create_client(server_name)
                        self.upstream_clients[server_name] = client
                    await self.fetch_upstream_tools(server_name)
                except Exception:
                    pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            asyncio.run(_fetch_all())

    async def initialize(self) -> None:
        """Initialize upstream connections."""
        if self._initialized:
            return

        for server_name in self.config.mcp_servers:
            if server_name not in self.upstream_clients:
                client = await self._create_client(server_name)
                self.upstream_clients[server_name] = client

        await self.refresh_upstream_tools()

        for view_name, view in self.views.items():
            await view.initialize(
                self.upstream_clients,
                get_client=self.get_active_client,
                reconnect_client=self.reconnect_client,
            )
            # Update tool mapping for dynamically discovered tools
            view_tools = self.get_view_tools(view_name)
            view.update_tool_mapping(view_tools)

        self._initialized = True

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

            if pre_hook:
                hook_result = await execute_pre_call(pre_hook, args, context)
                if hook_result.args:
                    args = hook_result.args

            result = await tool(**args)

            if post_hook:
                hook_result = await execute_post_call(post_hook, result, args, context)
                if hook_result.result is not None:
                    result = hook_result.result

            return result

        return wrapped

    def run(
        self,
        transport: str = "stdio",
        port: int | None = None,
        access_log: bool = True,
    ) -> None:  # pragma: no cover
        """Run the proxy server."""
        if transport == "stdio":
            # For stdio, fetch tools synchronously before starting
            self.sync_fetch_tools()
            aggregated_instructions = self.get_aggregated_instructions()
            stdio_server = FastMCP(
                "MCP Tool View Proxy",
                instructions=aggregated_instructions,
                lifespan=self._create_lifespan(),
            )
            default_tools = self.get_view_tools(None)
            # Use "default" view if it exists (for custom tools, hooks, etc.)
            default_view = self.views.get("default")
            self._register_tools_on_mcp(stdio_server, default_tools, view=default_view)
            self._register_instructions_tool(stdio_server)
            stdio_server.run(transport="stdio")
        else:
            import uvicorn

            # http_app() handles its own tool fetching
            app = self.http_app()
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port or 8000,
                ws="wsproto",
                access_log=access_log,
            )

    def get_view_tools(self, view_name: str | None) -> list[ToolInfo]:
        """Get the list of tools for a specific view.

        If view_name is None and a "default" view exists, that view's tools
        are returned (including custom tools). This ensures the root /mcp
        endpoint uses the default view configuration.
        """
        tools: list[ToolInfo] = []

        if view_name is None:
            # Use "default" view if it exists, otherwise return raw mcp_servers
            if "default" in self.views:
                return self.get_view_tools("default")

            # No default view: return all tools from mcp_servers directly
            for server_name, server_config in self.config.mcp_servers.items():
                upstream_tools = self._upstream_tools.get(server_name, [])
                if server_config.tools:
                    tools.extend(
                        _process_server_with_tools_config(
                            server_name, server_config, upstream_tools
                        )
                    )
                else:
                    tools.extend(_process_server_all_tools(server_name, upstream_tools))
            return tools

        if view_name not in self.views:
            raise ValueError(f"View '{view_name}' not found")

        view = self.views[view_name]
        view_config = view.config

        if view_config.include_all:
            for server_name, server_config in self.config.mcp_servers.items():
                upstream_tools = self._upstream_tools.get(server_name, [])
                if upstream_tools:
                    tools.extend(
                        _process_view_include_all_with_upstream(
                            server_name, upstream_tools, view_config, server_config
                        )
                    )
                elif server_config.tools:
                    tools.extend(
                        _process_view_include_all_fallback(
                            server_name, server_config, view_config
                        )
                    )
        else:
            tools.extend(
                _process_view_explicit_tools(
                    view_config, self._upstream_tools, self.config.mcp_servers
                )
            )

        # Add composite tools
        for comp_name, comp_tool in view.composite_tools.items():
            tools.append(
                ToolInfo(
                    name=comp_name,
                    description=comp_tool.description,
                    server="",
                    input_schema=comp_tool.input_schema,
                )
            )

        # Add custom tools
        for custom_name, custom_fn in view.custom_tools.items():
            description = getattr(custom_fn, "_tool_description", "")
            tools.append(
                ToolInfo(
                    name=custom_name,
                    description=description,
                    server="",
                )
            )

        return tools

    def get_view_mcp(self, view_name: str) -> FastMCP:
        """Get a FastMCP instance for a specific view."""
        if view_name not in self.views:
            raise ValueError(f"View '{view_name}' not found")

        view = self.views[view_name]
        view_config = view.config
        aggregated_instructions = self.get_aggregated_instructions()
        mcp = FastMCP(f"MCP Proxy - {view_name}", instructions=aggregated_instructions)

        # Always update tool mapping (needed for view.call_tool to work)
        view_tools = self.get_view_tools(view_name)
        view.update_tool_mapping(view_tools)

        if view_config.exposure_mode == "search":
            self._register_search_tool(mcp, view_name)
        else:
            self._register_tools_on_mcp(mcp, view_tools, view=view)

        # Register the get_server_instructions tool
        self._register_instructions_tool(mcp)

        return mcp

    def _register_instructions_tool(self, mcp: FastMCP) -> None:
        """Register the get_server_instructions tool on an MCP instance."""
        proxy = self  # Capture reference for closure

        def get_server_instructions() -> str:
            """Get aggregated instructions from all upstream MCP servers.

            Call this at the start of every session to understand how to use
            the memory tools and other available capabilities effectively.
            """
            instructions = proxy.get_aggregated_instructions()
            if instructions:
                return instructions
            return "No server instructions available."

        mcp.tool(
            name="get_server_instructions",
            description=(
                "Get instructions for using the available tools. "
                "Call this at the start of every session to understand "
                "how to use the memory tools and other capabilities effectively."
            ),
        )(get_server_instructions)

    def _register_search_tool(self, mcp: FastMCP, view_name: str) -> None:
        """Register the search and call meta-tools for a view."""
        from mcp_proxy.search import ToolSearcher

        view = self.views[view_name]
        view_tools = self.get_view_tools(view_name)
        tools_data = [
            {"name": t.name, "description": t.description} for t in view_tools
        ]
        searcher = ToolSearcher(view_name=view_name, tools=tools_data)
        search_tool = searcher.create_search_tool()

        search_name = f"{view_name}_search_tools"

        async def search_tools_wrapper(query: str = "", limit: int = 10) -> dict:
            return await search_tool(query=query, limit=limit)

        search_tools_wrapper.__name__ = search_name
        search_tools_wrapper.__doc__ = f"Search for tools in the {view_name} view"

        mcp.tool(
            name=search_name, description=f"Search for tools in the {view_name} view"
        )(search_tools_wrapper)

        call_name = f"{view_name}_call_tool"
        tool_names_list = [t.name for t in view_tools]

        def make_call_tool_wrapper(
            v: ToolView, valid_tools: list[str]
        ) -> Callable[..., Any]:
            async def call_tool_wrapper(
                tool_name: str, arguments: dict | None = None
            ) -> Any:
                if tool_name not in valid_tools:
                    raise ValueError(
                        f"Unknown tool '{tool_name}'. "
                        f"Use {view_name}_search_tools to find available tools."
                    )
                return await v.call_tool(tool_name, arguments or {})

            return call_tool_wrapper

        call_wrapper = make_call_tool_wrapper(view, tool_names_list)
        call_wrapper.__name__ = call_name
        call_wrapper.__doc__ = (
            f"Call a tool in the {view_name} view by name. "
            f"Use {view_name}_search_tools first to find available tools."
        )

        mcp.tool(
            name=call_name,
            description=(
                f"Call a tool in the {view_name} view by name. "
                f"Use {view_name}_search_tools first to find available tools."
            ),
        )(call_wrapper)

    def _register_tools_on_mcp(
        self, mcp: FastMCP, tools: list[ToolInfo], view: ToolView | None = None
    ) -> None:
        """Register tools on a FastMCP instance."""
        for tool_info in tools:
            _tool_name = tool_info.name
            _tool_server = tool_info.server
            _tool_desc = tool_info.description or f"Tool: {_tool_name}"
            _input_schema = tool_info.input_schema
            _tool_original_name = tool_info.original_name
            _param_config = tool_info.parameter_config

            if view and _tool_name in view.custom_tools:
                custom_fn = view.custom_tools[_tool_name]
                mcp.tool(name=_tool_name, description=_tool_desc)(custom_fn)
            elif view and _tool_name in view.composite_tools:
                parallel_tool = view.composite_tools[_tool_name]
                input_schema = parallel_tool.input_schema

                def make_composite_wrapper(
                    v: ToolView, name: str
                ) -> Callable[..., Any]:
                    async def composite_wrapper(**kwargs: Any) -> Any:
                        return await v.call_tool(name, kwargs)

                    return composite_wrapper

                wrapper = make_composite_wrapper(view, _tool_name)
                tool = create_tool_with_schema(
                    name=_tool_name,
                    description=_tool_desc,
                    input_schema=input_schema,
                    fn=wrapper,
                )
                mcp._tool_manager._tools[_tool_name] = tool
            elif view:
                self._register_view_tool(
                    mcp, view, _tool_name, _tool_desc, _input_schema, _param_config
                )
            else:
                self._register_direct_tool(
                    mcp,
                    _tool_name,
                    _tool_desc,
                    _input_schema,
                    _tool_original_name,
                    _tool_server,
                    _param_config,
                )

    def _register_view_tool(
        self,
        mcp: FastMCP,
        view: ToolView,
        tool_name: str,
        tool_desc: str,
        input_schema: dict[str, Any] | None,
        param_config: dict[str, Any] | None,
    ) -> None:
        """Register a regular upstream tool that routes through view.call_tool."""
        if input_schema:

            def make_upstream_wrapper_kwargs(
                v: ToolView, name: str, param_cfg: dict[str, Any] | None
            ) -> Callable[..., Any]:
                async def upstream_wrapper(**kwargs: Any) -> Any:
                    transformed = transform_args(kwargs, param_cfg)
                    return await v.call_tool(name, transformed)

                return upstream_wrapper

            wrapper = make_upstream_wrapper_kwargs(view, tool_name, param_config)
            tool = create_tool_with_schema(
                name=tool_name,
                description=tool_desc,
                input_schema=input_schema,
                fn=wrapper,
            )
            mcp._tool_manager._tools[tool_name] = tool
        else:

            def make_upstream_wrapper_dict(
                v: ToolView, name: str, param_cfg: dict[str, Any] | None
            ) -> Callable[..., Any]:
                async def upstream_wrapper(arguments: dict | None = None) -> Any:
                    transformed = transform_args(arguments or {}, param_cfg)
                    return await v.call_tool(name, transformed)

                return upstream_wrapper

            wrapper = make_upstream_wrapper_dict(view, tool_name, param_config)
            wrapper.__name__ = tool_name
            wrapper.__doc__ = tool_desc
            mcp.tool(name=tool_name, description=tool_desc)(wrapper)

    def _register_direct_tool(
        self,
        mcp: FastMCP,
        tool_name: str,
        tool_desc: str,
        input_schema: dict[str, Any] | None,
        original_name: str,
        server: str,
        param_config: dict[str, Any] | None,
    ) -> None:
        """Register a tool that routes directly through proxy's upstream clients."""
        if input_schema:

            def make_direct_wrapper_kwargs(
                proxy: "MCPProxy",
                orig_name: str,
                srv: str,
                param_cfg: dict[str, Any] | None,
            ) -> Callable[..., Any]:
                async def direct_wrapper(**kwargs: Any) -> Any:
                    if srv not in proxy.config.mcp_servers:
                        raise ValueError(f"Server '{srv}' not configured")
                    transformed = transform_args(kwargs, param_cfg)
                    active_client = proxy._active_clients.get(srv)
                    if active_client:
                        return await active_client.call_tool(orig_name, transformed)
                    client = proxy._create_client_from_config(
                        proxy.config.mcp_servers[srv]
                    )
                    async with client:
                        return await client.call_tool(orig_name, transformed)

                return direct_wrapper

            wrapper = make_direct_wrapper_kwargs(
                self, original_name, server, param_config
            )
            tool = create_tool_with_schema(
                name=tool_name,
                description=tool_desc,
                input_schema=input_schema,
                fn=wrapper,
            )
            mcp._tool_manager._tools[tool_name] = tool
        else:

            def make_direct_wrapper_dict(
                proxy: "MCPProxy",
                orig_name: str,
                srv: str,
                param_cfg: dict[str, Any] | None,
            ) -> Callable[..., Any]:
                async def direct_wrapper(arguments: dict | None = None) -> Any:
                    if srv not in proxy.config.mcp_servers:
                        raise ValueError(f"Server '{srv}' not configured")
                    transformed = transform_args(arguments or {}, param_cfg)
                    active_client = proxy._active_clients.get(srv)
                    if active_client:
                        return await active_client.call_tool(orig_name, transformed)
                    client = proxy._create_client_from_config(
                        proxy.config.mcp_servers[srv]
                    )
                    async with client:
                        return await client.call_tool(orig_name, transformed)

                return direct_wrapper

            wrapper = make_direct_wrapper_dict(
                self, original_name, server, param_config
            )
            wrapper.__name__ = tool_name
            wrapper.__doc__ = tool_desc
            mcp.tool(name=tool_name, description=tool_desc)(wrapper)

    def http_app(
        self,
        path: str = "",
        view_prefix: str = "/view",
        extra_routes: list[Route] | None = None,
    ) -> Starlette:
        """Create an ASGI app with multi-view routing.

        Tools are registered lazily in the lifespan after connecting to upstream
        servers. This ensures upstream processes are only spawned once (for
        persistent connections) rather than twice (once for tool discovery,
        once for connections).
        """
        from contextlib import asynccontextmanager

        from mcp_proxy.auth import create_auth_provider

        # Create auth provider from environment variables (if configured)
        auth_provider = create_auth_provider()

        # Create FastMCP instances - tools will be registered in the lifespan
        # Pass auth to each instance so FastMCP handles OAuth endpoints and validation
        default_mcp = FastMCP("MCP Proxy - Default", auth=auth_provider)
        view_mcps: dict[str, FastMCP] = {}
        for view_name in self.views:
            view_mcps[view_name] = FastMCP(
                f"MCP Proxy - {view_name}", auth=auth_provider
            )

        default_mcp_app = default_mcp.http_app(path="/mcp")

        view_mcp_apps: dict[str, Any] = {}
        for view_name, view_mcp in view_mcps.items():
            view_mcp_apps[view_name] = view_mcp.http_app(path="/mcp")

        @asynccontextmanager
        async def combined_lifespan(app: Starlette):  # pragma: no cover
            # Connect to upstream servers (spawns processes once)
            await self.connect_clients()

            # Fetch tools and instructions from active connections
            await self.fetch_tools_from_active_clients()

            # Now register tools on FastMCP instances
            aggregated_instructions = self.get_aggregated_instructions()
            default_mcp.instructions = aggregated_instructions

            # Root path uses "default" view if it exists (custom tools, hooks)
            default_view = self.views.get("default")
            if default_view:
                await default_view.initialize(
                    self.upstream_clients,
                    get_client=self.get_active_client,
                    reconnect_client=self.reconnect_client,
                )
                # get_view_tools(None) returns "default" view tools
                default_tools = self.get_view_tools(None)
                default_view.update_tool_mapping(default_tools)
                self._register_tools_on_mcp(
                    default_mcp, default_tools, view=default_view
                )
            else:
                default_tools = self.get_view_tools(None)
                self._register_tools_on_mcp(default_mcp, default_tools)
            self._register_instructions_tool(default_mcp)

            for view_name, view_mcp in view_mcps.items():
                # Skip "default" view - already initialized above for root
                if view_name == "default" and default_view:
                    view_tools = self.get_view_tools(view_name)
                    if default_view.config.exposure_mode == "search":
                        self._register_search_tool(view_mcp, view_name)
                    else:
                        self._register_tools_on_mcp(
                            view_mcp, view_tools, view=default_view
                        )
                    self._register_instructions_tool(view_mcp)
                    continue
                view_mcp.instructions = aggregated_instructions
                view = self.views[view_name]
                await view.initialize(
                    self.upstream_clients,
                    get_client=self.get_active_client,
                    reconnect_client=self.reconnect_client,
                )
                # Always update tool mapping (needed for view.call_tool to work)
                view_tools = self.get_view_tools(view_name)
                view.update_tool_mapping(view_tools)

                if view.config.exposure_mode == "search":
                    self._register_search_tool(view_mcp, view_name)
                else:
                    self._register_tools_on_mcp(view_mcp, view_tools, view=view)
                self._register_instructions_tool(view_mcp)

            try:
                async with default_mcp_app.lifespan(default_mcp_app):
                    yield
            finally:
                await self.disconnect_clients()

        routes: list[Route | Mount] = []

        # Add extra routes first (e.g., OAuth discovery endpoints)
        if extra_routes:
            routes.extend(extra_routes)

        async def health_check(request: Request) -> JSONResponse:
            return JSONResponse({"status": "healthy"})

        routes.append(Route(f"{path}/health", health_check, methods=["GET"]))

        async def view_info(request: Request) -> JSONResponse:
            view_name = request.path_params["view_name"]
            if view_name not in self.views:
                return JSONResponse(
                    {"error": f"View '{view_name}' not found"}, status_code=404
                )
            view = self.views[view_name]

            if view.config.exposure_mode == "search":
                tools_list = [{"name": f"{view_name}_search_tools"}]
            else:
                tools = self.get_view_tools(view_name)
                tools_list = [{"name": t.name} for t in tools] if tools else []

            return JSONResponse(
                {
                    "name": view_name,
                    "description": view.config.description,
                    "exposure_mode": view.config.exposure_mode,
                    "tools": tools_list,
                }
            )

        routes.append(Route(f"{path}/views/{{view_name}}", view_info, methods=["GET"]))

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

        for view_name, view_mcp_app in view_mcp_apps.items():
            routes.append(Mount(f"{path}{view_prefix}/{view_name}", app=view_mcp_app))

        if path:
            routes.append(Mount(path, app=default_mcp_app))
        else:
            routes.append(Mount("/", app=default_mcp_app))

        return Starlette(routes=routes, lifespan=combined_lifespan)
