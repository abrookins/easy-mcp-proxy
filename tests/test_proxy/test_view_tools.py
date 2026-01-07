"""Tests for get_view_tools method and upstream tool fetching."""

from unittest.mock import AsyncMock, MagicMock

import yaml

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyGetViewTools:
    """Tests for get_view_tools method."""

    def test_get_view_tools_with_dict_config(self):
        """get_view_tools should handle raw dict tool configs from YAML."""

        # Simulate raw YAML parsing - tool configs are dicts, not ToolConfig objects
        raw_yaml = """
mcp_servers:
  github:
    url: https://example.com
tool_views:
  research:
    description: Research view
    tools:
      github:
        search_code:
          description: Search code in repos
        list_issues:
          description: List issues
"""
        # Parse directly to simulate what load_config does internally
        raw_data = yaml.safe_load(raw_yaml)

        # Load through the normal config loader
        config = ProxyConfig(**raw_data)
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("research")

        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "search_code" in tool_names
        assert "list_issues" in tool_names

        # Check descriptions came through
        search_tool = next(t for t in tools if t.name == "search_code")
        assert search_tool.description == "Search code in repos"


class TestDefaultViewIncludesAllUpstreamTools:
    """Tests for default view including all tools from servers without tools config."""

    async def test_get_view_tools_none_uses_default_view_when_exists(self):
        """get_view_tools(None) should use 'default' view if it exists."""
        from mcp_proxy.custom_tools import custom_tool

        # Create a custom tool for the default view
        @custom_tool(name="my_custom_tool", description="A custom tool")
        async def my_custom_tool(query: str) -> dict:
            return {"result": query}

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "default": {
                    "include_all": True,
                    "custom_tools": [],  # We'll add custom tool to view directly
                }
            },
        )
        proxy = MCPProxy(config)

        # Add custom tool to the default view
        proxy.views["default"].custom_tools["my_custom_tool"] = my_custom_tool

        # Mock upstream tools
        mock_tool = MagicMock()
        mock_tool.name = "upstream_tool"
        mock_tool.description = "An upstream tool"
        mock_tool.inputSchema = {"type": "object"}

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        # get_view_tools(None) should now return tools from "default" view
        tools = proxy.get_view_tools(None)

        tool_names = [t.name for t in tools]
        assert "upstream_tool" in tool_names
        assert "my_custom_tool" in tool_names  # Custom tool from default view

    async def test_default_view_includes_all_tools_when_no_tools_config(self):
        """Default view should include ALL tools from servers without 'tools' config."""
        # Server has NO 'tools' key - should include all tools from upstream
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},  # No tools key
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool1.inputSchema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"
        mock_tool2.inputSchema = {
            "type": "object",
            "properties": {"y": {"type": "number"}},
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        # Fetch tools from upstream
        await proxy.fetch_upstream_tools("server")

        # Get default view tools (view_name=None)
        tools = proxy.get_view_tools(None)

        tool_names = [t.name for t in tools]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names
        assert len(tools) == 2

        # Check schemas are preserved
        tool_a = next(t for t in tools if t.name == "tool_a")
        assert tool_a.input_schema is not None
        assert tool_a.input_schema["properties"]["x"]["type"] == "string"

    async def test_default_view_filters_when_tools_config_exists(self):
        """Default view should only include configured tools when 'tools' is set."""
        # Server HAS 'tools' key - should only include those tools
        config = ProxyConfig(
            mcp_servers={
                "server": {
                    "command": "echo",
                    "tools": {"tool_a": {}},  # Only tool_a is configured
                }
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream has both tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool1.inputSchema = {"type": "object"}

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools(None)

        # Only tool_a should be in the list
        tool_names = [t.name for t in tools]
        assert "tool_a" in tool_names
        assert "tool_b" not in tool_names
        assert len(tools) == 1


class TestCreateToolInfoFromUpstream:
    """Tests for _create_tool_info_from_upstream function."""

    def test_create_tool_info_with_tool_config(self):
        """_create_tool_info_from_upstream should apply tool_config overrides."""
        from mcp_proxy.models import ToolConfig
        from mcp_proxy.proxy.tools import _create_tool_info_from_upstream

        # Create a mock upstream tool
        mock_tool = MagicMock()
        mock_tool.name = "original_name"
        mock_tool.description = "Original description"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }

        # Create tool config with overrides
        tool_config = ToolConfig(
            name="aliased_name",
            description="Custom description",
        )

        result = _create_tool_info_from_upstream(mock_tool, "test-server", tool_config)

        assert result.name == "aliased_name"
        assert result.description == "Custom description"
        assert result.original_name == "original_name"
        assert result.server == "test-server"

    def test_create_tool_info_without_tool_config(self):
        """_create_tool_info_from_upstream should use upstream values when no config."""
        from mcp_proxy.proxy.tools import _create_tool_info_from_upstream

        # Create a mock upstream tool
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "My tool description"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"x": {"type": "number"}},
        }

        result = _create_tool_info_from_upstream(mock_tool, "server")

        assert result.name == "my_tool"
        assert result.description == "My tool description"
        assert result.original_name == "my_tool"
        assert result.input_schema["properties"]["x"]["type"] == "number"


class TestProcessViewIncludeAllFallback:
    """Tests for _process_view_include_all_fallback function."""

    def test_include_all_with_no_server_tools(self):
        """include_all should return empty list if server has no tools configured."""
        from mcp_proxy.models import ToolViewConfig, UpstreamServerConfig
        from mcp_proxy.proxy.tools import _process_view_include_all_fallback

        # Server with no tools
        server_config = UpstreamServerConfig(command="echo")
        view_config = ToolViewConfig(include_all=True, tools={})

        result = _process_view_include_all_fallback(
            "server", server_config, view_config
        )

        assert result == []
