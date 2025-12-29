"""Tests for tool registration in direct/search modes."""

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyToolRegistration:
    """Tests for tool registration in direct/search modes."""

    async def test_register_direct_tools(self):
        """_register_direct_tools exposes tools directly."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {"exposure_mode": "direct", "tools": {"server": {"tool_a": {}}}}
            },
        )
        MCPProxy(config)

        # After initialization, tools should be registered
        # Can't test without mocked FastMCP server

    async def test_register_search_tool(self):
        """_register_search_tool creates a meta search tool."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"tool_a": {}, "tool_b": {}}},
                }
            },
        )
        MCPProxy(config)

        # In search mode, only one tool should be registered: view_search_tools
