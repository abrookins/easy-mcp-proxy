"""Tool search functionality for MCP Proxy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from mcp_proxy.proxy.tool_info import ToolRegistry

# Default threshold for fuzzy matching (0-100 scale)
DEFAULT_THRESHOLD = 60.0


class SearchTool:
    """A callable search tool that finds matching tools using fuzzy search."""

    def __init__(
        self,
        name: str,
        view_name: str,
        tools: list[dict[str, Any]] | "ToolRegistry",
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self.name = name
        self._view_name = view_name
        self._tools = tools
        self._threshold = threshold
        self.parameters = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find matching tools",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 25,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip (for pagination)",
                    "default": 0,
                },
            },
            "required": [],
        }

    def _current_tools(self, include_schema: bool) -> list[dict[str, Any]]:
        """Read one complete metadata snapshot for this search."""
        if not isinstance(self._tools, list):
            return self._tools.metadata(include_schema=include_schema)
        if include_schema:
            return self._tools
        return [
            {key: value for key, value in tool.items() if key != "inputSchema"}
            for tool in self._tools
        ]

    async def __call__(
        self,
        query: str = "",
        limit: int = 25,
        offset: int = 0,
        include_schema: bool = False,
    ) -> dict[str, Any]:
        """Search for tools matching the query using fuzzy matching."""
        tools = self._current_tools(include_schema)
        if not query:
            # Empty query returns all tools (paginated)
            total = len(tools)
            matches = tools[offset : offset + limit]
            return {"tools": matches, "total": total, "offset": offset, "limit": limit}

        # Score each tool using fuzzy matching
        scored: list[tuple[float, dict[str, Any]]] = []
        for tool in tools:
            name = tool.get("name", "")
            desc = tool.get("description", "")

            # Use partial_ratio for substring/partial matching
            name_score = fuzz.partial_ratio(query, name)
            desc_score = fuzz.partial_ratio(query, desc)
            best_score = max(name_score, desc_score)

            if best_score >= self._threshold:
                scored.append((best_score, tool))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Apply pagination
        total = len(scored)
        scored = scored[offset : offset + limit]

        matches = [tool for _, tool in scored]
        return {"tools": matches, "total": total, "offset": offset, "limit": limit}


class ToolSearcher:
    """Creates search tools for a view's tools."""

    def __init__(self, view_name: str, tools: list[dict[str, Any]] | "ToolRegistry"):
        self.view_name = view_name
        self.tools = tools

    def create_search_tool(self) -> SearchTool:
        """Create a search tool for this view's tools."""
        return SearchTool(
            name=f"{self.view_name}_search_tools",
            view_name=self.view_name,
            tools=self.tools,
        )
