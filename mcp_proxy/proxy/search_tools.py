"""Search tool registration for MCP Proxy.

This module provides functions for registering search and call meta-tools
that allow clients to discover and invoke tools dynamically.
"""

import json
from typing import TYPE_CHECKING, Any, Callable

from fastmcp import FastMCP
from rapidfuzz import fuzz, process

from mcp_proxy.search import ToolSearcher

if TYPE_CHECKING:
    from mcp_proxy.views import ToolView

    from .tool_info import ToolInfo

from .tool_info import ToolRegistry

TOOL_SUGGESTION_THRESHOLD = 70.0


class UnknownToolError(ValueError):
    """Structured lookup failure for an exposed tool name."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__(json.dumps(payload, sort_keys=True))


def create_call_tool_wrapper(
    view: "ToolView",
    tools: list["ToolInfo"] | dict[str, "ToolInfo"] | ToolRegistry,
    search_tool_name: str,
) -> Callable[..., Any]:
    """Create a call_tool wrapper function with validation.

    Args:
        view: The ToolView to call tools on
        tools: ToolInfo objects keyed by exposed tool name or a flat list
        search_tool_name: Name of the search tool for error messages

    Returns:
        An async function that validates and calls tools
    """
    tool_map = {tool.name: tool for tool in tools} if isinstance(tools, list) else tools

    async def call_tool_wrapper(
        tool_name: str, arguments: dict | str | None = None
    ) -> Any:
        tool_info = tool_map.get(tool_name)
        if tool_info is None:
            raise ValueError(
                f"Unknown tool '{tool_name}'. "
                f"Use {search_tool_name} to find available tools."
            )
        from .validation import normalize_and_validate_arguments

        normalized_args = normalize_and_validate_arguments(tool_info, arguments)
        return await view.call_tool(tool_name, normalized_args, tool_info=tool_info)

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

    async def search_wrapper(
        query: str = "",
        limit: int = 25,
        offset: int = 0,
        include_schema: bool = False,
    ) -> dict:
        return await search_tool(
            query=query,
            limit=limit,
            offset=offset,
            include_schema=include_schema,
        )

    search_wrapper.__name__ = name
    search_wrapper.__doc__ = description
    return search_wrapper


def create_describe_tool_wrapper(
    registry: ToolRegistry, name: str, entity_name: str
) -> Callable[..., Any]:
    """Create an exact, registry-backed description lookup tool."""

    async def describe_tool_wrapper(tool_name: str) -> dict[str, Any]:
        return lookup_tool_metadata(registry, tool_name, entity_name)

    describe_tool_wrapper.__name__ = name
    describe_tool_wrapper.__doc__ = (
        f"Describe one tool exposed by {entity_name}, including its input schema."
    )
    return describe_tool_wrapper


def lookup_tool_metadata(
    registry: ToolRegistry, tool_name: str, entity_name: str
) -> dict[str, Any]:
    """Return exact canonical metadata or raise a structured lookup error."""
    tool = registry.get(tool_name)
    if tool is not None:
        return tool.to_metadata(include_schema=True)

    available_names = sorted(item.name for item in registry.tools)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "error": "unknown_tool",
        "message": f"Unknown tool '{tool_name}' in '{entity_name}'.",
        "tool": tool_name,
        "available_tool_names": available_names,
    }
    match = process.extractOne(tool_name, available_names, scorer=fuzz.ratio)
    if match is not None and match[1] >= TOOL_SUGGESTION_THRESHOLD:
        payload["did_you_mean"] = match[0]
    raise UnknownToolError(payload)


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
    registry = view.replace_tool_registry(entity_name, tools)
    searcher = ToolSearcher(view_name=entity_name, tools=registry)
    search_tool = searcher.create_search_tool()

    search_name = f"{entity_name}_search_tools"
    preposition = "in" if entity_type == "view" else "from"
    search_desc = f"Search for tools {preposition} the {entity_name} {entity_type}"
    search_wrapper = create_search_wrapper(search_tool, search_name, search_desc)
    mcp.tool(name=search_name, description=f"{search_desc}.")(search_wrapper)

    describe_name = f"{entity_name}_describe_tool"
    describe_wrapper = create_describe_tool_wrapper(
        registry, describe_name, entity_name
    )
    mcp.tool(name=describe_name, description=describe_wrapper.__doc__)(describe_wrapper)

    call_name = f"{entity_name}_call_tool"
    call_wrapper = create_call_tool_wrapper(view, registry, search_name)
    call_wrapper.__name__ = call_name
    call_desc = (
        f"Call a tool {preposition} the {entity_name} {entity_type} by name. "
        f"Use {search_name} first to find available tools."
    )
    call_wrapper.__doc__ = call_desc
    mcp.tool(name=call_name, description=call_desc)(call_wrapper)
