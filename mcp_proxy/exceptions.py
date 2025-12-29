"""Exceptions for MCP Proxy."""


class ToolCallAborted(Exception):
    """Raised when a tool call is aborted by a pre-call hook."""

    def __init__(
        self,
        reason: str,
        tool_name: str | None = None,
        view_name: str | None = None,
    ):
        self.reason = reason
        self.tool_name = tool_name
        self.view_name = view_name
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason
