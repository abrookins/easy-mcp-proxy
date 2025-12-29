"""Tests for stdio server mode - verifies tools are registered on self.server."""

import pytest
from fastmcp import Client, FastMCP

from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy, ToolInfo


class TestStdioServerIntegration:
    """Tests for stdio server mode - verifies tools are registered on self.server."""

    @pytest.mark.asyncio
    async def test_stdio_server_has_tools_registered(self):
        """self.server (used for stdio) should have tools registered at init."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_a": {"description": "Tool A"},
                        "tool_b": {"description": "Tool B"},
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Use in-memory client to verify tools are registered on self.server
        async with Client(proxy.server) as client:
            tools = await client.list_tools()
            assert len(tools) == 2
            tool_names = [t.name for t in tools]
            assert "tool_a" in tool_names
            assert "tool_b" in tool_names

    @pytest.mark.asyncio
    async def test_stdio_server_tool_descriptions(self):
        """stdio server should have correct tool descriptions."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={"my_tool": {"description": "My special tool"}},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        async with Client(proxy.server) as client:
            tools = await client.list_tools()
            my_tool = next(t for t in tools if t.name == "my_tool")
            assert my_tool.description == "My special tool"

    @pytest.mark.asyncio
    async def test_get_view_tools_unknown_view_raises(self):
        """get_view_tools() should raise ValueError for unknown view."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="View 'nonexistent' not found"):
            proxy.get_view_tools("nonexistent")

    @pytest.mark.asyncio
    async def test_get_view_tools_handles_dict_config(self):
        """get_view_tools() should handle tool config as dict."""
        # When config is loaded from YAML, tool configs are dicts, not ToolConfig
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                )
            },
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {"description": "Search code in repos"},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # This should work with dict tool config
        tools = proxy.get_view_tools("research")
        assert len(tools) == 1
        assert tools[0].name == "search_code"
        assert tools[0].description == "Search code in repos"

    @pytest.mark.asyncio
    async def test_tool_requires_configured_server(self):
        """Tools require server to be configured to execute."""
        from fastmcp.exceptions import ToolError

        # Create config with no servers
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # Manually register a tool that references a non-existent server
        tools = [
            ToolInfo(
                name="my_tool",
                description="My tool",
                server="nonexistent",
                original_name="my_tool",
            )
        ]
        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools)

        # Call the tool - should error because server is not configured
        async with Client(test_mcp) as client:
            with pytest.raises(ToolError, match="not configured"):
                await client.call_tool("my_tool", {})
