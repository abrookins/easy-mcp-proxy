"""Tests for ToolSearcher (search exposure mode)."""

import pytest


class TestToolSearcher:
    """Tests for the ToolSearcher class."""

    def test_create_search_tool(self):
        """ToolSearcher.create_search_tool() returns a callable tool."""
        from mcp_proxy.search import ToolSearcher

        # Mock tools list
        tools = [
            {"name": "search_memory", "description": "Search long-term memory"},
            {"name": "create_memory", "description": "Create a new memory"},
        ]

        searcher = ToolSearcher(view_name="redis-expert", tools=tools)
        search_tool = searcher.create_search_tool()

        assert search_tool.name == "redis-expert_search_tools"
        assert callable(search_tool)

    async def test_search_tool_returns_matching_tools(self):
        """Search tool should return tools matching the query."""
        from mcp_proxy.search import ToolSearcher

        tools = [
            {"name": "search_memory", "description": "Search long-term memory"},
            {"name": "create_memory", "description": "Create a new memory"},
            {"name": "delete_file", "description": "Delete a file"},
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        # Search for "memory" should return 2 tools
        result = await search_tool(query="memory")

        assert len(result["tools"]) == 2
        assert all("memory" in t["name"] or "memory" in t["description"].lower()
                   for t in result["tools"])

    async def test_search_tool_empty_query_returns_all(self):
        """Empty query should return all tools in the view."""
        from mcp_proxy.search import ToolSearcher

        tools = [
            {"name": "tool_a", "description": "First tool"},
            {"name": "tool_b", "description": "Second tool"},
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        result = await search_tool(query="")

        assert len(result["tools"]) == 2

    async def test_search_tool_no_matches(self):
        """Search with no matches returns empty list."""
        from mcp_proxy.search import ToolSearcher

        tools = [
            {"name": "search_memory", "description": "Search memories"},
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        result = await search_tool(query="github")

        assert len(result["tools"]) == 0

    async def test_search_tool_respects_limit(self):
        """Search should respect the limit parameter."""
        from mcp_proxy.search import ToolSearcher

        tools = [
            {"name": "tool_1", "description": "First tool"},
            {"name": "tool_2", "description": "Second tool"},
            {"name": "tool_3", "description": "Third tool"},
            {"name": "tool_4", "description": "Fourth tool"},
            {"name": "tool_5", "description": "Fifth tool"},
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        result = await search_tool(query="tool", limit=3)

        assert len(result["tools"]) == 3

    def test_search_tool_includes_schema(self):
        """Search results should include tool schemas."""
        from mcp_proxy.search import ToolSearcher

        tools = [
            {
                "name": "search_memory",
                "description": "Search memories",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    }
                }
            },
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        # The search tool's schema should be properly defined
        assert search_tool.parameters is not None
        assert "query" in search_tool.parameters.get("properties", {})

