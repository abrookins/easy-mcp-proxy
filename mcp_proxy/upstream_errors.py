"""Helpers for classifying upstream call failures."""

import asyncio

from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError


def is_retriable_upstream_error(exc: Exception) -> bool:
    """Return whether an upstream call failure is likely transport-related.

    MCP protocol and tool errors are deterministic responses from the upstream
    server. Retrying them can duplicate work and obscures the original failure
    with nested tracebacks.
    """
    non_retriable = (McpError, ToolError, TimeoutError, asyncio.TimeoutError)
    return not isinstance(exc, non_retriable)
