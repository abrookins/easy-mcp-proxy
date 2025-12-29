"""Main MCP Proxy class."""

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Callable

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from fastmcp.server.tasks.config import TaskConfig
from fastmcp.tools.tool import FunctionTool
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
from mcp_proxy.models import ProxyConfig, ToolConfig, UpstreamServerConfig
from mcp_proxy.utils import expand_env_vars
from mcp_proxy.views import ToolView


def _create_tool_with_schema(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    fn: Callable[..., Any],
) -> FunctionTool:
    """Create a FastMCP FunctionTool with a custom input schema.

    Args:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for tool inputs
        fn: The wrapper function to call

    Returns:
        A FunctionTool instance with the custom schema
    """
    return FunctionTool(
        name=name,
        description=description,
        fn=fn,
        parameters=input_schema,
        enabled=True,
        tags=set(),
        task_config=TaskConfig(),
    )


def _transform_schema(
    schema: dict[str, Any] | None,
    tool_config: ToolConfig | None,
) -> dict[str, Any] | None:
    """Transform an input schema based on parameter configuration.

    Handles:
    - Hiding parameters (removes from schema)
    - Renaming parameters (changes property name)
    - Overriding parameter descriptions
    - Setting default values (makes parameter optional)

    Args:
        schema: Original JSON Schema for tool inputs
        tool_config: Tool configuration with parameter overrides

    Returns:
        Transformed schema, or original if no changes needed
    """
    if schema is None or tool_config is None or not tool_config.parameters:
        return schema

    # Deep copy to avoid mutating the original
    import copy
    new_schema = copy.deepcopy(schema)

    properties = new_schema.get("properties", {})
    required = new_schema.get("required", [])

    for param_name, param_config in tool_config.parameters.items():
        if param_name not in properties:
            continue

        if param_config.hidden:
            # Remove hidden parameter from schema
            del properties[param_name]
            if param_name in required:
                required.remove(param_name)
        elif param_config.rename:
            # Rename the parameter
            prop_value = properties.pop(param_name)
            if param_config.description:
                prop_value["description"] = param_config.description
            if param_config.default is not None:
                prop_value["default"] = param_config.default
            properties[param_config.rename] = prop_value
            if param_name in required:
                required.remove(param_name)
                # If there's a default, don't add to required
                if param_config.default is None:
                    required.append(param_config.rename)
        else:
            # Update description and/or default without renaming
            if param_config.description:
                properties[param_name]["description"] = param_config.description
            if param_config.default is not None:
                properties[param_name]["default"] = param_config.default
                # Remove from required if we have a default
                if param_name in required:
                    required.remove(param_name)

    new_schema["properties"] = properties
    new_schema["required"] = required

    return new_schema


def _transform_args(
    args: dict[str, Any],
    parameter_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Transform arguments based on parameter configuration.

    Handles:
    - Injecting default values for hidden parameters
    - Injecting default values for missing optional parameters
    - Mapping renamed parameters back to original names

    Args:
        args: Arguments as passed by the caller (using exposed param names)
        parameter_config: Dict mapping original param names to their config

    Returns:
        Transformed arguments ready for the upstream tool
    """
    if parameter_config is None:
        return args

    new_args = dict(args)

    for param_name, config in parameter_config.items():
        if config.get("hidden"):
            # Inject default value for hidden parameter
            if config.get("default") is not None:
                new_args[param_name] = config["default"]
        elif config.get("rename"):
            # Map renamed parameter back to original name
            renamed = config["rename"]
            if renamed in new_args:
                new_args[param_name] = new_args.pop(renamed)
            elif config.get("default") is not None and param_name not in new_args:
                # Inject default if renamed param not provided
                new_args[param_name] = config["default"]
        elif config.get("default") is not None and param_name not in new_args:
            # Inject default for non-renamed optional param
            new_args[param_name] = config["default"]

    return new_args


class ToolInfo:
    """Simple class to hold tool information."""

    def __init__(
        self,
        name: str,
        description: str = "",
        server: str = "",
        input_schema: dict[str, Any] | None = None,
        original_name: str | None = None,
        parameter_config: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.server = server
        self.input_schema = input_schema
        # original_name is the upstream tool name if this tool was aliased
        self.original_name = original_name if original_name else name
        # parameter_config stores the ParameterConfig for each param (for arg transformation)
        self.parameter_config = parameter_config

    def __repr__(self) -> str:
        return f"ToolInfo(name={self.name!r}, server={self.server!r})"


class MCPProxy:
    """MCP Proxy that aggregates and filters tools from upstream servers."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self.views: dict[str, ToolView] = {}
        self.upstream_clients: dict[str, Client] = {}
        self._upstream_tools: dict[str, list[Any]] = {}  # Cached tools from upstreams
        self._initialized = False
        self._active_clients: dict[str, Client] = {}  # Clients with active connections
        self._exit_stack: AsyncExitStack | None = None  # Manages client lifecycles

        self.server = FastMCP("MCP Tool View Proxy")

        # Create views from config
        for view_name, view_config in config.tool_views.items():
            self.views[view_name] = ToolView(name=view_name, config=view_config)

        # Register stub tools on the default server (for stdio transport)
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(self.server, default_tools)

    def _create_lifespan(self) -> Callable:
        """Create a lifespan context manager that initializes upstream connections."""

        @asynccontextmanager
        async def proxy_lifespan(mcp: FastMCP):
            """Initialize upstream connections on server startup."""
            await self.initialize()
            yield

        return proxy_lifespan

    def sync_fetch_tools(self) -> None:
        """Synchronously fetch tools from all upstream servers.

        This method blocks until all upstream servers have been contacted
        and their tool schemas retrieved. Call this before registering
        tools if you need schema information.
        """
        import asyncio

        async def _fetch_all():
            for server_name in self.config.mcp_servers:
                try:
                    if server_name not in self.upstream_clients:
                        client = await self._create_client(server_name)
                        self.upstream_clients[server_name] = client
                    await self.fetch_upstream_tools(server_name)
                except Exception:
                    # Log but continue - missing schemas fall back to generic
                    pass

        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            # Not in an event loop, safe to use asyncio.run()
            asyncio.run(_fetch_all())
        # If already in a loop, skip - tools will be fetched during initialize()

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
        their tool lists. Does NOT establish persistent connections -
        use connect_clients() for that.
        """
        if self._initialized:
            return

        for server_name in self.config.mcp_servers:
            if server_name not in self.upstream_clients:
                client = await self._create_client(server_name)
                self.upstream_clients[server_name] = client

        # Fetch tools from all upstream servers to populate schemas
        await self.refresh_upstream_tools()

        # Initialize views with upstream clients
        # Views will use get_active_client() for tool calls
        for view in self.views.values():
            await view.initialize(self.upstream_clients, get_client=self.get_active_client)

        self._initialized = True

    async def connect_clients(self) -> None:
        """Establish persistent connections to all upstream servers.

        This enters the async context for each client, keeping the connections
        (and stdio subprocesses) alive until disconnect_clients() is called.
        Should be called during server lifespan startup.
        """
        if self._exit_stack is not None:
            return  # Already connected

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for server_name in self.config.mcp_servers:
            try:
                # Create a fresh client for the persistent connection
                client = self._create_client_from_config(
                    self.config.mcp_servers[server_name]
                )
                # Enter the client context - this starts the connection/subprocess
                await self._exit_stack.enter_async_context(client)
                self._active_clients[server_name] = client
            except Exception:
                # Log but continue - some servers may be unavailable
                pass

    async def disconnect_clients(self) -> None:
        """Close all persistent client connections.

        This exits the async context for all clients, terminating
        stdio subprocesses. Should be called during server lifespan shutdown.
        """
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
            self._active_clients.clear()

    def get_active_client(self, server_name: str) -> Client | None:
        """Get an active (connected) client for a server.

        Args:
            server_name: Name of the server

        Returns:
            Connected client if available, None otherwise
        """
        return self._active_clients.get(server_name)

    def has_active_connection(self, server_name: str) -> bool:
        """Check if there's an active connection to a server.

        Args:
            server_name: Name of the server

        Returns:
            True if an active connection exists
        """
        return server_name in self._active_clients

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
        if server_name not in self.config.mcp_servers:
            raise ValueError(f"No client for server '{server_name}'")

        # Use active client if available (connection pooling)
        active_client = self._active_clients.get(server_name)
        if active_client:
            return await active_client.call_tool(tool_name, args)

        # Fall back to creating a fresh client for each call
        client = self._create_client_from_config(self.config.mcp_servers[server_name])
        async with client:
            return await client.call_tool(tool_name, args)

    async def refresh_upstream_tools(self) -> None:
        """Refresh tool lists from all upstream servers.

        Errors connecting to individual servers are logged but don't
        prevent other servers from being contacted. Tools from servers
        that can't be reached will have no schema information.
        """
        for server_name in self.upstream_clients:
            try:
                await self.fetch_upstream_tools(server_name)
            except Exception:
                # Log error but continue - tool will work without schema
                pass

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
        # Pre-fetch tools from upstream servers to get their schemas
        self.sync_fetch_tools()

        if transport == "stdio":
            # Create a new FastMCP server with lifespan for stdio transport
            # This initializes upstream connections before the server starts
            stdio_server = FastMCP(
                "MCP Tool View Proxy", lifespan=self._create_lifespan()
            )
            # Register tools on the new server (now with schemas from sync_fetch_tools)
            default_tools = self.get_view_tools(None)
            self._register_tools_on_mcp(stdio_server, default_tools)
            stdio_server.run(transport="stdio")
        else:
            # For HTTP transport, use http_app() which has tools registered
            import uvicorn

            app = self.http_app()
            # Use wsproto instead of websockets to avoid deprecation warnings
            uvicorn.run(app, host="0.0.0.0", port=port or 8000, ws="wsproto")

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
                    # Server has explicit tool config - use filtered/renamed tools
                    # Get upstream tools for schemas
                    upstream_tools = self._upstream_tools.get(server_name, [])
                    upstream_by_name = {t.name: t for t in upstream_tools}

                    for tool_name, tool_config in server_config.tools.items():
                        # Get schema from upstream if available
                        upstream_tool = upstream_by_name.get(tool_name)
                        tool_schema = getattr(upstream_tool, "inputSchema", None) if upstream_tool else None
                        upstream_desc = getattr(upstream_tool, "description", "") if upstream_tool else ""

                        # Transform schema based on parameter config
                        transformed_schema = _transform_schema(tool_schema, tool_config)
                        param_config = (
                            {k: v.model_dump() for k, v in tool_config.parameters.items()}
                            if tool_config.parameters else None
                        )

                        # Handle aliases: if aliases defined, create multiple tools
                        if tool_config.aliases:
                            for alias in tool_config.aliases:
                                tools.append(ToolInfo(
                                    name=alias.name,
                                    description=alias.description or upstream_desc,
                                    server=server_name,
                                    input_schema=transformed_schema,
                                    original_name=tool_name,
                                    parameter_config=param_config,
                                ))
                        else:
                            # Single tool (possibly renamed)
                            exposed_name = tool_config.name if tool_config.name else tool_name
                            description = tool_config.description or upstream_desc
                            tools.append(ToolInfo(
                                name=exposed_name,
                                description=description,
                                server=server_name,
                                input_schema=transformed_schema,
                                original_name=tool_name,
                                parameter_config=param_config,
                            ))
                else:
                    # No tools config - include ALL tools from upstream
                    upstream_tools = self._upstream_tools.get(server_name, [])
                    for upstream_tool in upstream_tools:
                        tool_name = upstream_tool.name
                        tool_description = getattr(upstream_tool, "description", "") or ""
                        tool_schema = getattr(upstream_tool, "inputSchema", None)
                        tools.append(ToolInfo(
                            name=tool_name,
                            description=tool_description,
                            server=server_name,
                            input_schema=tool_schema,
                            original_name=tool_name,
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
                # Prefer actual tools fetched from upstream, fall back to config
                upstream_tools = self._upstream_tools.get(server_name, [])
                if upstream_tools:
                    # Use actual tools from upstream server
                    for upstream_tool in upstream_tools:
                        tool_name = upstream_tool.name
                        tool_description = getattr(upstream_tool, "description", "") or ""
                        tool_schema = getattr(upstream_tool, "inputSchema", None)

                        # Check if view has override for this tool
                        view_override = None
                        if server_name in view_config.tools:
                            view_override = view_config.tools[server_name].get(tool_name)

                        # Get effective tool_config for parameter transformation
                        effective_config = view_override or (
                            server_config.tools.get(tool_name) if server_config.tools else None
                        )
                        transformed_schema = _transform_schema(tool_schema, effective_config)
                        param_config = (
                            {k: v.model_dump() for k, v in effective_config.parameters.items()}
                            if effective_config and effective_config.parameters else None
                        )

                        if view_override and view_override.aliases:
                            # Handle aliases from view override
                            for alias in view_override.aliases:
                                tools.append(ToolInfo(
                                    name=alias.name,
                                    description=alias.description or tool_description,
                                    server=server_name,
                                    input_schema=transformed_schema,
                                    original_name=tool_name,
                                    parameter_config=param_config,
                                ))
                        elif view_override:
                            exposed_name = view_override.name or tool_name
                            description = view_override.description or tool_description
                            tools.append(ToolInfo(
                                name=exposed_name,
                                description=description,
                                server=server_name,
                                input_schema=transformed_schema,
                                original_name=tool_name,
                                parameter_config=param_config,
                            ))
                        else:
                            tools.append(ToolInfo(
                                name=tool_name,
                                description=tool_description,
                                server=server_name,
                                input_schema=transformed_schema,
                                original_name=tool_name,
                                parameter_config=param_config,
                            ))
                elif server_config.tools:
                    # Fall back to config-defined tools if upstream not fetched
                    for tool_name, tool_config in server_config.tools.items():
                        view_override = None
                        if server_name in view_config.tools:
                            view_override = view_config.tools[server_name].get(tool_name)

                        # Determine effective config (view override takes precedence)
                        effective_config = view_override or tool_config
                        transformed_schema = _transform_schema(None, effective_config)
                        param_config = (
                            {k: v.model_dump() for k, v in effective_config.parameters.items()}
                            if effective_config.parameters else None
                        )

                        # Handle aliases
                        if effective_config.aliases:
                            for alias in effective_config.aliases:
                                tools.append(ToolInfo(
                                    name=alias.name,
                                    description=alias.description or "",
                                    server=server_name,
                                    original_name=tool_name,
                                    input_schema=transformed_schema,
                                    parameter_config=param_config,
                                ))
                        else:
                            exposed_name = effective_config.name or tool_name
                            description = effective_config.description or ""
                            tools.append(ToolInfo(
                                name=exposed_name,
                                description=description,
                                server=server_name,
                                original_name=tool_name,
                                input_schema=transformed_schema,
                                parameter_config=param_config,
                            ))
        else:
            # Only include explicitly listed tools
            for server_name, server_tools in view_config.tools.items():
                # Get upstream tools for this server to find schemas
                upstream_tools = self._upstream_tools.get(server_name, [])
                upstream_by_name = {t.name: t for t in upstream_tools}

                for tool_name, tool_config in server_tools.items():
                    # Get schema and description from upstream if available
                    upstream_tool = upstream_by_name.get(tool_name)
                    if upstream_tool:
                        tool_schema = getattr(upstream_tool, "inputSchema", None)
                        upstream_desc = getattr(upstream_tool, "description", "") or ""
                    else:
                        tool_schema = None
                        upstream_desc = ""

                    # Transform schema based on parameter config
                    transformed_schema = _transform_schema(tool_schema, tool_config)
                    param_config = (
                        {k: v.model_dump() for k, v in tool_config.parameters.items()}
                        if tool_config.parameters else None
                    )

                    # Handle aliases
                    if tool_config.aliases:
                        for alias in tool_config.aliases:
                            tools.append(ToolInfo(
                                name=alias.name,
                                description=alias.description or upstream_desc,
                                server=server_name,
                                input_schema=transformed_schema,
                                original_name=tool_name,
                                parameter_config=param_config,
                            ))
                    else:
                        exposed_name = tool_config.name if tool_config.name else tool_name
                        description = tool_config.description or upstream_desc
                        tools.append(ToolInfo(
                            name=exposed_name,
                            description=description,
                            server=server_name,
                            input_schema=transformed_schema,
                            original_name=tool_name,
                            parameter_config=param_config,
                        ))

        # Add composite tools
        for comp_name, comp_tool in view.composite_tools.items():
            tools.append(ToolInfo(
                name=comp_name,
                description=comp_tool.description,
                server="",  # Composite tools don't have a single server
                input_schema=comp_tool.input_schema,
            ))

        # Add custom tools
        for custom_name, custom_fn in view.custom_tools.items():
            description = getattr(custom_fn, "_tool_description", "")
            tools.append(ToolInfo(
                name=custom_name,
                description=description,
                server="",  # Custom tools don't have an upstream server
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
        """Register the search and call meta-tools for a view."""
        from mcp_proxy.search import ToolSearcher

        view = self.views[view_name]
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

        # Register the call_tool meta-tool to execute found tools
        call_name = f"{view_name}_call_tool"
        tool_names_list = [t.name for t in view_tools]

        def make_call_tool_wrapper(v: ToolView, valid_tools: list[str]) -> Callable[..., Any]:
            async def call_tool_wrapper(tool_name: str, arguments: dict | None = None) -> Any:
                """Call a tool by name with the given arguments."""
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
            )
        )(call_wrapper)

    def _register_tools_on_mcp(
        self, mcp: FastMCP, tools: list[ToolInfo], view: ToolView | None = None
    ) -> None:
        """Register tools on a FastMCP instance.

        If a view is provided, registers callable tools that route through the view.
        Otherwise, registers stub tools (for backward compatibility).
        """
        for tool_info in tools:
            # Capture tool_info in closure
            _tool_name = tool_info.name
            _tool_server = tool_info.server
            _tool_desc = tool_info.description or f"Tool: {_tool_name}"
            _input_schema = tool_info.input_schema
            _tool_original_name = tool_info.original_name
            _param_config = tool_info.parameter_config

            if view and _tool_name in view.custom_tools:
                # Register actual custom tool
                custom_fn = view.custom_tools[_tool_name]
                mcp.tool(name=_tool_name, description=_tool_desc)(custom_fn)
            elif view and _tool_name in view.composite_tools:
                # Register composite tool wrapper that routes through view.call_tool
                parallel_tool = view.composite_tools[_tool_name]
                input_schema = parallel_tool.input_schema

                def make_composite_wrapper(
                    v: ToolView, name: str
                ) -> Callable[..., Any]:
                    async def composite_wrapper(**kwargs: Any) -> Any:
                        """Call composite tool with arguments."""
                        return await v.call_tool(name, kwargs)

                    return composite_wrapper

                wrapper = make_composite_wrapper(view, _tool_name)
                tool = _create_tool_with_schema(
                    name=_tool_name,
                    description=_tool_desc,
                    input_schema=input_schema,
                    fn=wrapper,
                )
                mcp._tool_manager._tools[_tool_name] = tool
            elif view:
                # Regular upstream tool - route through view.call_tool
                if _input_schema:
                    # Create wrapper that takes **kwargs for use with custom schema

                    def make_upstream_wrapper_kwargs(
                        v: ToolView, name: str, param_cfg: dict[str, Any] | None
                    ) -> Callable[..., Any]:
                        async def upstream_wrapper(**kwargs: Any) -> Any:
                            """Call upstream tool with arguments."""
                            transformed = _transform_args(kwargs, param_cfg)
                            return await v.call_tool(name, transformed)

                        return upstream_wrapper

                    wrapper = make_upstream_wrapper_kwargs(view, _tool_name, _param_config)
                    tool = _create_tool_with_schema(
                        name=_tool_name,
                        description=_tool_desc,
                        input_schema=_input_schema,
                        fn=wrapper,
                    )
                    mcp._tool_manager._tools[_tool_name] = tool
                else:
                    # Fall back to generic registration with dict argument

                    def make_upstream_wrapper_dict(
                        v: ToolView, name: str, param_cfg: dict[str, Any] | None
                    ) -> Callable[..., Any]:
                        async def upstream_wrapper(arguments: dict | None = None) -> Any:
                            """Call upstream tool with arguments."""
                            transformed = _transform_args(arguments or {}, param_cfg)
                            return await v.call_tool(name, transformed)

                        return upstream_wrapper

                    wrapper = make_upstream_wrapper_dict(view, _tool_name, _param_config)
                    wrapper.__name__ = _tool_name
                    wrapper.__doc__ = _tool_desc
                    mcp.tool(name=_tool_name, description=_tool_desc)(wrapper)
            else:
                # No view provided - route directly through proxy's upstream clients
                if _input_schema:
                    # Create wrapper that takes **kwargs for use with custom schema

                    def make_direct_wrapper_kwargs(
                        proxy: "MCPProxy",
                        original_name: str,
                        server: str,
                        param_cfg: dict[str, Any] | None,
                    ) -> Callable[..., Any]:
                        async def direct_wrapper(**kwargs: Any) -> Any:
                            """Call upstream tool directly via proxy."""
                            if server not in proxy.config.mcp_servers:
                                raise ValueError(f"Server '{server}' not configured")
                            transformed = _transform_args(kwargs, param_cfg)
                            # Use active client if available (connection pooling)
                            active_client = proxy._active_clients.get(server)
                            if active_client:
                                return await active_client.call_tool(
                                    original_name, transformed
                                )
                            # Fall back to creating a fresh client
                            client = proxy._create_client_from_config(
                                proxy.config.mcp_servers[server]
                            )
                            async with client:
                                return await client.call_tool(original_name, transformed)

                        return direct_wrapper

                    wrapper = make_direct_wrapper_kwargs(
                        self, _tool_original_name, _tool_server, _param_config
                    )
                    tool = _create_tool_with_schema(
                        name=_tool_name,
                        description=_tool_desc,
                        input_schema=_input_schema,
                        fn=wrapper,
                    )
                    mcp._tool_manager._tools[_tool_name] = tool
                else:
                    # Fall back to generic registration with dict argument

                    def make_direct_wrapper_dict(
                        proxy: "MCPProxy",
                        original_name: str,
                        server: str,
                        param_cfg: dict[str, Any] | None,
                    ) -> Callable[..., Any]:
                        async def direct_wrapper(arguments: dict | None = None) -> Any:
                            """Call upstream tool directly via proxy."""
                            if server not in proxy.config.mcp_servers:
                                raise ValueError(f"Server '{server}' not configured")
                            transformed = _transform_args(arguments or {}, param_cfg)
                            # Use active client if available (connection pooling)
                            active_client = proxy._active_clients.get(server)
                            if active_client:
                                return await active_client.call_tool(
                                    original_name, transformed
                                )
                            # Fall back to creating a fresh client
                            client = proxy._create_client_from_config(
                                proxy.config.mcp_servers[server]
                            )
                            async with client:
                                return await client.call_tool(original_name, transformed)

                        return direct_wrapper

                    wrapper = make_direct_wrapper_dict(
                        self, _tool_original_name, _tool_server, _param_config
                    )
                    wrapper.__name__ = _tool_name
                    wrapper.__doc__ = _tool_desc
                    mcp.tool(name=_tool_name, description=_tool_desc)(wrapper)

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

        # Pre-fetch tools from upstream servers to get their schemas
        self.sync_fetch_tools()

        # Create FastMCP instances for default and each view
        default_mcp = FastMCP("MCP Proxy - Default")

        # Register tools from all mcp_servers on default MCP (now with schemas)
        default_tools = self.get_view_tools(None)
        self._register_tools_on_mcp(default_mcp, default_tools)

        view_mcps: dict[str, FastMCP] = {}
        for view_name in self.views:
            # Use get_view_mcp to properly handle search mode and pass view for routing
            view_mcp = self.get_view_mcp(view_name)
            view_mcps[view_name] = view_mcp

        # Get MCP HTTP apps
        default_mcp_app = default_mcp.http_app(path="/mcp")

        view_mcp_apps: dict[str, Any] = {}
        for view_name, view_mcp in view_mcps.items():
            view_mcp_apps[view_name] = view_mcp.http_app(path="/mcp")

        # Create combined lifespan that handles all MCP apps
        @asynccontextmanager
        async def combined_lifespan(app: Starlette):  # pragma: no cover
            # Initialize upstream connections (creates clients, fetches tool schemas)
            await self.initialize()
            # Establish persistent connections to upstream servers
            # This keeps stdio subprocesses alive for the lifetime of the server
            await self.connect_clients()
            try:
                # Use the default MCP app's lifespan for session management
                async with default_mcp_app.lifespan(default_mcp_app):
                    yield
            finally:
                # Clean up persistent connections on shutdown
                await self.disconnect_clients()

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
