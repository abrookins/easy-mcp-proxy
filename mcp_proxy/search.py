"""Tool search functionality for MCP Proxy."""

from typing import Any


class SearchTool:
    """A callable search tool that finds matching tools."""

    def __init__(self, name: str, view_name: str, tools: list[dict[str, Any]]):
        self.name = name
        self._view_name = view_name
        self._tools = tools
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

    async def __call__(
        self, query: str, limit: int | None = None
    ) -> dict[str, Any]:
        """Search for tools matching the query."""
        query_lower = query.lower()

        if not query:
            # Empty query returns all tools
            matches = self._tools
        else:
            matches = []
            for tool in self._tools:
                name = tool.get("name", "").lower()
                desc = tool.get("description", "").lower()
                if query_lower in name or query_lower in desc:
                    matches.append(tool)

        if limit is not None:
            matches = matches[:limit]

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

