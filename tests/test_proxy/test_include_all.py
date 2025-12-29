"""Tests for include_all fetching actual tools from upstream servers."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp_proxy.models import (
    ProxyConfig,
    UpstreamServerConfig,
    ToolConfig,
    ToolViewConfig,
)
from mcp_proxy.proxy import MCPProxy


class TestIncludeAllFetchesFromUpstream:
    """Tests for include_all fetching actual tools from upstream servers."""

    async def test_include_all_uses_upstream_tools(self):
        """include_all: true should include tools from upstream, not just config."""
        # Config has include_all: true but no tools defined in config
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "include_all": True,
                    "tools": {},  # No tools defined in config
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock the upstream client that returns actual tools
        mock_tool = MagicMock()
        mock_tool.name = "upstream_tool"
        mock_tool.description = "A tool from upstream"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        # Fetch tools from upstream (simulates what happens during initialization)
        await proxy.fetch_upstream_tools("server")

        # Now get view tools - should include the upstream tool
        tools = proxy.get_view_tools("view")

        # FAILING ASSERTION: Currently returns empty because config has no tools
        tool_names = [t.name for t in tools]
        assert "upstream_tool" in tool_names, (
            f"Expected 'upstream_tool' in {tool_names}"
        )

    async def test_include_all_with_no_config_tools_still_works(self):
        """include_all should work even when server has no tools in config."""
        # Server has no 'tools' key at all in config
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},  # No tools key
            tool_views={"view": {"include_all": True, "tools": {}}},
        )
        proxy = MCPProxy(config)

        # Mock upstream returns tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools("view")
        tool_names = [t.name for t in tools]

        # Should include both upstream tools
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    @pytest.mark.asyncio
    async def test_include_all_with_view_override_for_upstream_tool(self):
        """include_all should apply view overrides to upstream tools."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(url="http://example.com")},
            tool_views={
                "view": ToolViewConfig(
                    include_all=True,
                    # Override tool_a with custom name and description
                    tools={
                        "server": {
                            "tool_a": ToolConfig(
                                name="renamed_tool_a", description="Custom description"
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream tools
        mock_tool = MagicMock()
        mock_tool.name = "tool_a"
        mock_tool.description = "Original description"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools("view")
        tool_names = [t.name for t in tools]
        tool_descs = {t.name: t.description for t in tools}

        # Should use overridden name and description
        assert "renamed_tool_a" in tool_names
        assert "tool_a" not in tool_names
        assert tool_descs["renamed_tool_a"] == "Custom description"

