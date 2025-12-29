"""Tool views for MCP Proxy."""

from typing import Any, Callable

from mcp_proxy.custom_tools import ProxyContext, load_custom_tool
from mcp_proxy.exceptions import ToolCallAborted
from mcp_proxy.hooks import (
    HookResult,
    ToolCallContext,
    execute_post_call,
    execute_pre_call,
    load_hook,
)
from mcp_proxy.models import ToolConfig, ToolViewConfig
from mcp_proxy.parallel import ParallelTool


class ToolView:
    """A view that exposes a filtered subset of tools from upstream servers."""

    def __init__(self, name: str, config: ToolViewConfig):
        self.name = name
        self.config = config
        self.description = config.description
        self._pre_call_hook: Callable | None = None
        self._post_call_hook: Callable | None = None
        self._tool_to_server: dict[str, str] = {}
        self._tool_to_original_name: dict[str, str] = {}  # renamed -> original
        self._upstream_clients: dict[str, Any] = {}
        self._get_client: Callable[[str], Any | None] | None = None  # Get active client
        self.composite_tools: dict[str, ParallelTool] = {}
        self.custom_tools: dict[str, Callable] = {}

        # Build tool-to-server mapping, handling renames
        for server_name, tools in config.tools.items():
            for tool_name, tool_config in tools.items():
                # If tool has a name override, use that as the exposed name
                exposed_name = tool_config.name if tool_config.name else tool_name
                self._tool_to_server[exposed_name] = server_name
                if tool_config.name:
                    # Track the rename mapping
                    self._tool_to_original_name[exposed_name] = tool_name

        # Load composite tools from config
        for comp_name, comp_config in config.composite_tools.items():
            self.composite_tools[comp_name] = ParallelTool.from_config(
                comp_name,
                {
                    "description": comp_config.description,
                    "inputs": comp_config.inputs,
                    "parallel": comp_config.parallel,
                }
            )

        # Load custom tools from config
        for custom_config in config.custom_tools:
            if "module" in custom_config:
                tool_fn = load_custom_tool(custom_config["module"])
                tool_name = getattr(tool_fn, "_tool_name", tool_fn.__name__)
                self.custom_tools[tool_name] = tool_fn

    async def initialize(
        self,
        upstream_clients: dict[str, Any],
        get_client: Callable[[str], Any | None] | None = None,
    ) -> None:
        """Initialize the view with upstream clients.

        Args:
            upstream_clients: Dict mapping server names to existing clients (for compatibility)
            get_client: Optional function to get an active (connected) client for a server name.
                       If provided and returns a client, that client will be used directly.
                       Otherwise falls back to stored clients.
        """
        self._upstream_clients = upstream_clients
        self._get_client = get_client
        self._load_hooks()

        # Verify we have clients for all referenced servers
        for server_name in self.config.tools.keys():
            if server_name not in upstream_clients:
                raise ValueError(f"Missing client for server: {server_name}")

    def _load_hooks(self) -> None:
        """Load hook functions from dotted paths."""
        if self.config.hooks:
            if self.config.hooks.pre_call:
                self._pre_call_hook = load_hook(self.config.hooks.pre_call)
            if self.config.hooks.post_call:
                self._post_call_hook = load_hook(self.config.hooks.post_call)

    def _get_server_for_tool(self, tool_name: str) -> str:
        """Get the upstream server name for a tool."""
        return self._tool_to_server.get(tool_name, "")

    def _transform_tool(self, tool: Any, config: ToolConfig) -> Any:
        """Transform a tool with name/description overrides."""
        # Create a simple wrapper with transformed attributes
        class TransformedTool:
            pass

        transformed = TransformedTool()
        transformed.name = config.name if config.name else tool.name
        original_desc = getattr(tool, "description", "")
        if config.description:
            transformed.description = config.description.replace(
                "{original}", original_desc
            )
        else:
            transformed.description = original_desc
        return transformed

    def _get_original_tool_name(self, exposed_name: str) -> str:
        """Get the original tool name for a possibly-renamed tool."""
        return self._tool_to_original_name.get(exposed_name, exposed_name)

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool, applying hooks if configured."""
        # Check if it's a custom tool
        if tool_name in self.custom_tools:
            return await self._call_custom_tool(tool_name, args)

        # Check if it's a composite tool
        if tool_name in self.composite_tools:
            return await self._call_composite_tool(tool_name, args)

        server_name = self._get_server_for_tool(tool_name)

        context = ToolCallContext(
            view_name=self.name,
            tool_name=tool_name,
            upstream_server=server_name,
        )

        # Apply pre-call hook
        if self._pre_call_hook:
            hook_result = await execute_pre_call(self._pre_call_hook, args, context)
            if hook_result.abort:
                raise ToolCallAborted(
                    reason=hook_result.abort_reason or "Aborted",
                    tool_name=tool_name,
                    view_name=self.name,
                )
            if hook_result.args:
                args = hook_result.args

        # Call upstream
        if not server_name or server_name not in self._upstream_clients:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Use the original tool name when calling upstream (handles renames)
        original_name = self._get_original_tool_name(tool_name)

        # Try to get an active (connected) client first
        active_client = self._get_client(server_name) if self._get_client else None
        if active_client:
            # Use the active client directly (no context manager needed)
            result = await active_client.call_tool(original_name, args)
        else:
            # Fall back to stored client with context manager
            client = self._upstream_clients[server_name]
            async with client:
                result = await client.call_tool(original_name, args)

        # Apply post-call hook
        if self._post_call_hook:
            hook_result = await execute_post_call(
                self._post_call_hook, result, args, context
            )
            if hook_result.result is not None:
                result = hook_result.result

        return result

    async def _call_upstream_tool(self, upstream_tool: str, **kwargs: Any) -> Any:
        """Call an upstream tool by server.tool_name format.

        Args:
            upstream_tool: Tool reference in "server.tool_name" format
            **kwargs: Arguments to pass to the tool

        Returns:
            Result from the upstream tool call

        Raises:
            ValueError: If the tool format is invalid or server not found
        """
        if "." not in upstream_tool:
            raise ValueError(f"Unknown upstream tool: {upstream_tool}")

        server, tool = upstream_tool.split(".", 1)
        if server not in self._upstream_clients:
            raise ValueError(f"Unknown upstream tool: {upstream_tool}")

        # Try to get an active (connected) client first
        active_client = self._get_client(server) if self._get_client else None
        if active_client:
            # Use the active client directly (no context manager needed)
            return await active_client.call_tool(tool, kwargs)
        else:
            # Fall back to stored client with context manager
            client = self._upstream_clients[server]
            async with client:
                return await client.call_tool(tool, kwargs)

    async def _call_custom_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Call a custom tool with ProxyContext."""
        tool_fn = self.custom_tools[tool_name]

        ctx = ProxyContext(
            call_tool_fn=self._call_upstream_tool,
            available_tools=list(self._tool_to_server.keys()),
        )

        # Call the custom tool with context
        return await tool_fn(ctx=ctx, **args)

    async def _call_composite_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a composite (parallel) tool."""
        parallel_tool = self.composite_tools[tool_name]
        parallel_tool._call_tool_fn = self._call_upstream_tool
        return await parallel_tool.execute(args)

