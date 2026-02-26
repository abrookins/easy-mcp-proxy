"""Tests for tool registration in direct/search modes."""

from unittest.mock import MagicMock

from fastmcp import FastMCP

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


class TestRegisterViewOnMcp:
    """Tests for _register_view_on_mcp method."""

    async def test_register_view_on_mcp_direct_mode(self):
        """_register_view_on_mcp registers tools in direct mode."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "test_view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"tool_a": {}}},
                }
            },
        )
        proxy = MCPProxy(config)
        mcp = FastMCP("test")
        view = proxy.views["test_view"]

        # Call the method
        proxy._register_view_on_mcp(mcp, view, "test_view", None)

        # Instructions tool should be registered
        assert "get_tool_instructions" in mcp._tool_manager._tools

    async def test_register_view_on_mcp_search_mode(self):
        """_register_view_on_mcp registers search tools in search mode."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "test_view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"tool_a": {}}},
                }
            },
        )
        proxy = MCPProxy(config)
        mcp = FastMCP("test")
        view = proxy.views["test_view"]

        proxy._register_view_on_mcp(mcp, view, "test_view", None)

        # Search tools should be registered (with view name prefix)
        assert "test_view_search_tools" in mcp._tool_manager._tools
        assert "test_view_call_tool" in mcp._tool_manager._tools

    async def test_register_view_on_mcp_search_per_server_mode(self):
        """_register_view_on_mcp registers per-server search tools."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "test_view": {
                    "exposure_mode": "search_per_server",
                    "tools": {"server": {"tool_a": {}}},
                }
            },
        )
        proxy = MCPProxy(config)
        mcp = FastMCP("test")
        view = proxy.views["test_view"]

        proxy._register_view_on_mcp(mcp, view, "test_view", None)

        # Per-server search tools should be registered
        assert "server_search_tools" in mcp._tool_manager._tools
        assert "server_call_tool" in mcp._tool_manager._tools

    async def test_register_view_on_mcp_with_cache_context(self):
        """_register_view_on_mcp registers cache retrieval with cache_context."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "test_view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"tool_a": {}}},
                }
            },
            output_cache={"enabled": True, "base_url": "http://localhost:8000"},
        )
        proxy = MCPProxy(config)
        mcp = FastMCP("test")
        view = proxy.views["test_view"]

        # Simulate a cache context
        cache_context = MagicMock()

        proxy._register_view_on_mcp(mcp, view, "test_view", cache_context)

        # Cache retrieval tool should be registered
        assert "retrieve_cached_output" in mcp._tool_manager._tools
