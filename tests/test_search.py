"""Tests for ToolSearcher (search exposure mode)."""

import pytest

from mcp_proxy.search import DEFAULT_THRESHOLD, SearchTool, ToolSearcher


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


class TestFuzzySearch:
    """Tests for fuzzy matching in tool search."""

    async def test_fuzzy_match_partial_words(self):
        """Fuzzy search should match partial words in tool names."""
        tools = [
            {"name": "get_month_category_budget", "description": "Get budget"},
            {"name": "list_accounts", "description": "List all accounts"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=60.0
        )

        # "month categories" should match "get_month_category_budget"
        result = await search_tool(query="month categories")

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "get_month_category_budget"

    async def test_fuzzy_match_description(self):
        """Fuzzy search should match against descriptions."""
        tools = [
            {"name": "tool_a", "description": "Manage user authentication settings"},
            {"name": "tool_b", "description": "Delete files"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=60.0
        )

        result = await search_tool(query="auth settings")

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "tool_a"

    async def test_fuzzy_results_sorted_by_score(self):
        """Results should be sorted by match score, best first."""
        tools = [
            {"name": "xyz_unrelated", "description": "Something else"},
            {"name": "search_memory", "description": "Search in memory"},
            {"name": "memory", "description": "Memory tool"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=50.0
        )

        result = await search_tool(query="memory")

        # Results should be sorted - exact name match "memory" first
        assert len(result["tools"]) >= 2
        # First result should have "memory" in name (highest score)
        assert "memory" in result["tools"][0]["name"].lower()

    async def test_fuzzy_threshold_filters_low_scores(self):
        """Tools below threshold should not be returned."""
        tools = [
            {"name": "get_weather", "description": "Get weather forecast"},
            {"name": "xyz_unrelated", "description": "Something completely different"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=60.0
        )

        result = await search_tool(query="weather forecast")

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "get_weather"

    async def test_custom_threshold(self):
        """SearchTool should respect custom threshold."""
        tools = [
            {"name": "memory_search", "description": "Search memories"},
            {"name": "xyz_random", "description": "Completely unrelated tool"},
        ]

        # High threshold - only very close matches
        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=90.0
        )

        result = await search_tool(query="memory")

        # Only memory_search should match at 90% threshold
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "memory_search"

    async def test_default_threshold_value(self):
        """Default threshold should be 60."""
        assert DEFAULT_THRESHOLD == 60.0

        tools = [{"name": "test_tool", "description": "A test"}]
        search_tool = SearchTool(name="test", view_name="test", tools=tools)
        assert search_tool._threshold == 60.0

    async def test_empty_name_and_description(self):
        """Search should handle tools with empty name/description."""
        tools = [
            {"name": "", "description": ""},
            {"name": "real_tool", "description": "A real tool"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=60.0
        )

        result = await search_tool(query="real")

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "real_tool"

    async def test_empty_query_with_limit(self):
        """Empty query with limit should return limited results."""
        tools = [
            {"name": "tool_1", "description": "First"},
            {"name": "tool_2", "description": "Second"},
            {"name": "tool_3", "description": "Third"},
        ]

        search_tool = SearchTool(
            name="test_search", view_name="test", tools=tools, threshold=60.0
        )

        result = await search_tool(query="", limit=2)

        assert len(result["tools"]) == 2

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
        assert all(
            "memory" in t["name"] or "memory" in t["description"].lower()
            for t in result["tools"]
        )

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
                    "properties": {"query": {"type": "string"}},
                },
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
                    "tools": {"server": {"tool_a": {}, "tool_b": {}}},
                }
            },
        )
        proxy = MCPProxy(config)

        view_mcp = proxy.get_view_mcp("view")

        # Should have search tool
        tool_names = [t.name for t in view_mcp._tool_manager._tools.values()]
        assert "view_search_tools" in tool_names

        # FAILING ASSERTION: Should also have call_tool meta-tool
        assert "view_call_tool" in tool_names, (
            "Search mode should register view_call_tool to allow calling found tools"
        )

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
                    "tools": {
                        "server": {"search_code": {"description": "Search code"}}
                    },
                }
            },
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
        result = await call_tool_fn(
            tool_name="search_code", arguments={"query": "test"}
        )

        # Should have called upstream
        mock_client.call_tool.assert_called_once_with("search_code", {"query": "test"})
        assert result == {"results": ["file1.py", "file2.py"]}

    @pytest.mark.asyncio
    async def test_call_tool_raises_for_unknown_tool(self):
        """call_tool meta-tool should raise ValueError for unknown tools."""
        from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="http://example.com",
                    tools={"search_code": {"description": "Search code"}},
                )
            },
            tool_views={
                "view": ToolViewConfig(
                    exposure_mode="search", tools={"github": {"search_code": {}}}
                )
            },
        )
        proxy = MCPProxy(config)
        mcp = proxy.get_view_mcp("view")

        # Find the call_tool function
        call_tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "view_call_tool":
                call_tool_fn = tool.fn
                break

        assert call_tool_fn is not None

        # Call with unknown tool name should raise
        with pytest.raises(ValueError, match="Unknown tool 'nonexistent'"):
            await call_tool_fn(tool_name="nonexistent", arguments={})


class TestSearchPerServerMode:
    """Tests for search_per_server exposure mode."""

    async def test_search_per_server_creates_tools_for_each_server(self):
        """search_per_server should create search/call pairs for each server."""
        from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(command="echo"),
                "memory": UpstreamServerConfig(command="echo"),
            },
            tool_views={
                "all": ToolViewConfig(
                    exposure_mode="search_per_server",
                    tools={
                        "github": {"search_code": {}, "list_issues": {}},
                        "memory": {"search_memories": {}, "create_memory": {}},
                    },
                )
            },
        )
        proxy = MCPProxy(config)
        view_mcp = proxy.get_view_mcp("all")

        tool_names = [t.name for t in view_mcp._tool_manager._tools.values()]

        # Should have search/call for each server
        assert "github_search_tools" in tool_names
        assert "github_call_tool" in tool_names
        assert "memory_search_tools" in tool_names
        assert "memory_call_tool" in tool_names

        # Should NOT have individual tools
        assert "search_code" not in tool_names
        assert "list_issues" not in tool_names
        assert "search_memories" not in tool_names

    async def test_search_per_server_search_returns_server_tools_only(self):
        """Each server's search tool should only return that server's tools."""
        import json

        from fastmcp import Client

        from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "search_code": {"description": "Search GitHub code"},
                        "list_issues": {"description": "List GitHub issues"},
                    },
                ),
                "memory": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "search_memories": {"description": "Search memories"},
                    },
                ),
            },
            tool_views={
                "all": ToolViewConfig(
                    exposure_mode="search_per_server",
                    tools={
                        "github": {"search_code": {}, "list_issues": {}},
                        "memory": {"search_memories": {}},
                    },
                )
            },
        )
        proxy = MCPProxy(config)
        view_mcp = proxy.get_view_mcp("all")

        async with Client(view_mcp) as client:
            # Search github tools
            result = await client.call_tool("github_search_tools", {"query": ""})
            content = result.content[0].text if result.content else "{}"
            data = json.loads(content)

            # Should only return github tools
            assert len(data["tools"]) == 2
            tool_names = [t["name"] for t in data["tools"]]
            assert "search_code" in tool_names
            assert "list_issues" in tool_names
            assert "search_memories" not in tool_names

    async def test_search_per_server_call_tool_validates_server(self):
        """Each server's call_tool should only accept that server's tools."""
        from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(command="echo"),
                "memory": UpstreamServerConfig(command="echo"),
            },
            tool_views={
                "all": ToolViewConfig(
                    exposure_mode="search_per_server",
                    tools={
                        "github": {"search_code": {}},
                        "memory": {"search_memories": {}},
                    },
                )
            },
        )
        proxy = MCPProxy(config)
        view_mcp = proxy.get_view_mcp("all")

        # Find github's call_tool function
        github_call_fn = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "github_call_tool":
                github_call_fn = tool.fn
                break

        assert github_call_fn is not None

        # Should reject memory tools
        with pytest.raises(ValueError, match="Unknown tool 'search_memories'"):
            await github_call_fn(tool_name="search_memories", arguments={})

    async def test_search_per_server_with_include_all(self):
        """search_per_server should work with include_all: true."""
        from unittest.mock import MagicMock

        from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy import MCPProxy

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(command="echo"),
                "memory": UpstreamServerConfig(command="echo"),
            },
            tool_views={
                "all": ToolViewConfig(
                    exposure_mode="search_per_server",
                    include_all=True,
                )
            },
        )
        proxy = MCPProxy(config)

        # Simulate upstream tools being discovered
        mock_github_tool = MagicMock()
        mock_github_tool.name = "search_code"
        mock_github_tool.description = "Search code"

        mock_memory_tool = MagicMock()
        mock_memory_tool.name = "search_memories"
        mock_memory_tool.description = "Search memories"

        proxy._upstream_tools = {
            "github": [mock_github_tool],
            "memory": [mock_memory_tool],
        }

        view_mcp = proxy.get_view_mcp("all")
        tool_names = [t.name for t in view_mcp._tool_manager._tools.values()]

        # Should have per-server search tools
        assert "github_search_tools" in tool_names
        assert "memory_search_tools" in tool_names
