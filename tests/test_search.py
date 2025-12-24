"""Tests for ToolSearcher (search exposure mode)."""

import pytest

from mcp_proxy.search import ToolSearcher


class TestToolSearcher:
    """Tests for the ToolSearcher class."""

    def test_create_search_tool(self):
        """ToolSearcher.create_search_tool() returns a callable tool."""
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
        tools = [
            {"name": "search_memory", "description": "Search memories"},
        ]

        searcher = ToolSearcher(view_name="test", tools=tools)
        search_tool = searcher.create_search_tool()

        result = await search_tool(query="github")

        assert len(result["tools"]) == 0

    async def test_search_tool_respects_limit(self):
        """Search should respect the limit parameter."""
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


class TestSearchModeCallThrough:
    """Tests for calling tools after searching in search mode."""

    async def test_search_mode_has_call_tool_meta(self):
        """Search mode should register a call_tool meta-tool alongside search."""
        from mcp_proxy.models import ProxyConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"tool_a": {}, "tool_b": {}}}
                }
            }
        )
        proxy = MCPProxy(config)

        view_mcp = proxy.get_view_mcp("view")

        # Should have search tool
        tool_names = [t.name for t in view_mcp._tool_manager._tools.values()]
        assert "view_search_tools" in tool_names

        # FAILING ASSERTION: Should also have call_tool meta-tool
        assert "view_call_tool" in tool_names, \
            "Search mode should register view_call_tool to allow calling found tools"

    async def test_search_mode_call_tool_executes_upstream(self):
        """The call_tool meta-tool should execute the specified tool."""
        from unittest.mock import AsyncMock
        from mcp_proxy.models import ProxyConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"search_code": {"description": "Search code"}}}
                }
            }
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"results": ["file1.py", "file2.py"]}
        proxy.upstream_clients = {"server": mock_client}
        # Also inject into the view
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        view_mcp = proxy.get_view_mcp("view")

        # Find the call_tool meta-tool
        call_tool_fn = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "view_call_tool":
                call_tool_fn = tool.fn
                break

        # call_tool should exist
        assert call_tool_fn is not None, "view_call_tool should be registered"

        # Call the meta-tool to execute search_code
        result = await call_tool_fn(tool_name="search_code", arguments={"query": "test"})

        # Should have called upstream
        mock_client.call_tool.assert_called_once_with("search_code", {"query": "test"})
        assert result == {"results": ["file1.py", "file2.py"]}

