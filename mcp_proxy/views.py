"""Tool views for MCP Proxy."""

from typing import Any, Callable

from mcp_proxy.exceptions import ToolCallAborted
from mcp_proxy.hooks import (
    HookResult,
    ToolCallContext,
    execute_post_call,
    execute_pre_call,
    load_hook,
)
from mcp_proxy.models import ToolConfig, ToolViewConfig


class ToolView:
    """A view that exposes a filtered subset of tools from upstream servers."""

    def __init__(self, name: str, config: ToolViewConfig):
        self.name = name
        self.config = config
        self.description = config.description
        self._pre_call_hook: Callable | None = None
        self._post_call_hook: Callable | None = None
        self._tool_to_server: dict[str, str] = {}
        self._upstream_clients: dict[str, Any] = {}

        # Build tool-to-server mapping
        for server_name, tools in config.tools.items():
            for tool_name in tools.keys():
                self._tool_to_server[tool_name] = server_name

    async def initialize(self, upstream_clients: dict[str, Any]) -> None:
        """Initialize the view with upstream clients."""
        self._upstream_clients = upstream_clients
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

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool, applying hooks if configured."""
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

        client = self._upstream_clients[server_name]
        result = await client.call_tool(tool_name, args)

        # Apply post-call hook
        if self._post_call_hook:
            hook_result = await execute_post_call(
                self._post_call_hook, result, args, context
            )
            if hook_result.result is not None:
                result = hook_result.result

        return result

