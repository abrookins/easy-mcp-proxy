"""Search tool registration for MCP Proxy.

This module provides functions for registering search and call meta-tools
that allow clients to discover and invoke tools dynamically.
"""

from typing import TYPE_CHECKING, Any, Callable

from fastmcp import FastMCP

from mcp_proxy.search import ToolSearcher

if TYPE_CHECKING:
    from mcp_proxy.views import ToolView

    from .tool_info import ToolInfo


def create_call_tool_wrapper(
    view: "ToolView",
    valid_tools: set[str] | list[str],
    search_tool_name: str,
) -> Callable[..., Any]:
    """Create a call_tool wrapper function with validation.

    Args:
        view: The ToolView to call tools on
        valid_tools: Set or list of valid tool names
        search_tool_name: Name of the search tool for error messages

    Returns:
        An async function that validates and calls tools
    """
    valid_set = set(valid_tools) if isinstance(valid_tools, list) else valid_tools

    async def call_tool_wrapper(tool_name: str, arguments: dict | None = None) -> Any:
        if tool_name not in valid_set:
            raise ValueError(
                f"Unknown tool '{tool_name}'. "
                f"Use {search_tool_name} to find available tools."
            )
        return await view.call_tool(tool_name, arguments or {})

    return call_tool_wrapper


def create_search_wrapper(
    search_tool: Callable, name: str, description: str
) -> Callable[..., Any]:
    """Create a search wrapper function.

    Args:
        search_tool: The search tool function to wrap
        name: Name for the wrapper function
        description: Description for the wrapper function

    Returns:
        An async function that wraps the search tool
    """

    async def search_wrapper(query: str = "", limit: int = 25, offset: int = 0) -> dict:
        return await search_tool(query=query, limit=limit, offset=offset)

    search_wrapper.__name__ = name
    search_wrapper.__doc__ = description
    return search_wrapper


def register_tool_pair(
    mcp: FastMCP,
    view: "ToolView",
    tools: list["ToolInfo"],
    entity_name: str,
    entity_type: str,
) -> None:
    """Register a search/call tool pair for a view or server.

    Args:
        mcp: FastMCP instance to register tools on
        view: ToolView for calling tools
        tools: List of tools to expose
        entity_name: Name of the view or server
        entity_type: Either "view" or "server" for descriptions
    """
    tools_data = [{"name": t.name, "description": t.description} for t in tools]
    searcher = ToolSearcher(view_name=entity_name, tools=tools_data)
    search_tool = searcher.create_search_tool()

    search_name = f"{entity_name}_search_tools"
    preposition = "in" if entity_type == "view" else "from"
    search_desc = f"Search for tools {preposition} the {entity_name} {entity_type}"
    search_wrapper = create_search_wrapper(search_tool, search_name, search_desc)
    mcp.tool(name=search_name, description=f"{search_desc}.")(search_wrapper)

    call_name = f"{entity_name}_call_tool"
    tool_names = {t.name for t in tools}
    call_wrapper = create_call_tool_wrapper(view, tool_names, search_name)
    call_wrapper.__name__ = call_name
    call_desc = (
        f"Call a tool {preposition} the {entity_name} {entity_type} by name. "
        f"Use {search_name} first to find available tools."
    )
    call_wrapper.__doc__ = call_desc
    mcp.tool(name=call_name, description=call_desc)(call_wrapper)
