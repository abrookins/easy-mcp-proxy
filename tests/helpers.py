"""Test helpers for interacting with FastMCP public APIs."""

from typing import Any

from fastmcp import FastMCP


async def get_tool_names(mcp: FastMCP) -> set[str]:
    """Return registered tool names from FastMCP."""
    return {tool.name for tool in await mcp.list_tools()}


async def get_required_tool(mcp: FastMCP, name: str) -> Any:
    """Return a registered FastMCP tool, failing clearly if it is missing."""
    tool = await mcp.get_tool(name)
    assert tool is not None
    return tool
