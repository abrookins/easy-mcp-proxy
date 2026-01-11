"""Tool search functionality for MCP Proxy."""

from typing import Any

from rapidfuzz import fuzz

# Default threshold for fuzzy matching (0-100 scale)
DEFAULT_THRESHOLD = 60.0


class SearchTool:
    """A callable search tool that finds matching tools using fuzzy search."""

    def __init__(
        self,
        name: str,
        view_name: str,
        tools: list[dict[str, Any]],
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
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    async def __call__(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """Search for tools matching the query using fuzzy matching."""
        if not query:
            # Empty query returns all tools
            matches = self._tools
            if limit is not None:
                matches = matches[:limit]
            return {"tools": matches}

        # Score each tool using fuzzy matching
        scored: list[tuple[float, dict[str, Any]]] = []
        for tool in self._tools:
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

        # Apply limit
        if limit is not None:
            scored = scored[:limit]

        matches = [tool for _, tool in scored]
        return {"tools": matches}


class ToolSearcher:
    """Creates search tools for a view's tools."""

    def __init__(self, view_name: str, tools: list[dict[str, Any]]):
        self.view_name = view_name
        self.tools = tools

    def create_search_tool(self) -> SearchTool:
        """Create a search tool for this view's tools."""
        return SearchTool(
            name=f"{self.view_name}_search_tools",
            view_name=self.view_name,
            tools=self.tools,
        )
