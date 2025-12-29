"""Tests for tool name aliasing at the mcp_servers and view levels."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import Client

from mcp_proxy.models import (
    ProxyConfig,
    UpstreamServerConfig,
    ToolConfig,
    ToolViewConfig,
    AliasConfig,
)
from mcp_proxy.proxy import MCPProxy


class TestToolNameAliasing:
    """Tests for tool name aliasing at the mcp_servers level."""

    def test_get_view_tools_applies_name_alias_in_default_view(self):
        """get_view_tools should apply name alias from server config in default view."""
        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",
                    args=["test"],
                    tools={
                        "original_tool": ToolConfig(
                            name="aliased_tool", description="Test description"
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].name == "aliased_tool"
        assert tools[0].original_name == "original_tool"
        assert tools[0].description == "Test description"

    def test_get_view_tools_preserves_name_when_no_alias(self):
        """get_view_tools should use original name when no alias specified."""
        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",
                    tools={"my_tool": ToolConfig(description="No alias")},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].name == "my_tool"
        assert tools[0].original_name == "my_tool"

    def test_get_view_tools_multiple_tools_with_mixed_aliases(self):
        """get_view_tools should handle mix of aliased and non-aliased tools."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_a": ToolConfig(name="renamed_a", description="A"),
                        "tool_b": ToolConfig(description="B"),
                        "tool_c": ToolConfig(name="renamed_c", description="C"),
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        by_name = {t.name: t for t in tools}

        assert "renamed_a" in by_name
        assert by_name["renamed_a"].original_name == "tool_a"

        assert "tool_b" in by_name
        assert by_name["tool_b"].original_name == "tool_b"

        assert "renamed_c" in by_name
        assert by_name["renamed_c"].original_name == "tool_c"

    @pytest.mark.asyncio
    async def test_aliased_tool_calls_upstream_with_original_name(self):
        """Aliased tools should call upstream using original tool name."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={
                        "original_tool_name": ToolConfig(
                            name="aliased_tool_name", description="An aliased tool"
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create mock upstream client
        mock_upstream = MagicMock()
        mock_upstream.__aenter__ = AsyncMock(return_value=mock_upstream)
        mock_upstream.__aexit__ = AsyncMock(return_value=None)
        mock_upstream.call_tool = AsyncMock(return_value={"result": "success"})

        # Mock _create_client_from_config to return our mock client
        with patch.object(
            proxy, "_create_client_from_config", return_value=mock_upstream
        ):
            # Call using the aliased name
            async with Client(proxy.server) as client:
                # The tool is exposed as "aliased_tool_name"
                result = await client.call_tool(
                    "aliased_tool_name", {"arguments": {"key": "value"}}
                )

            # But upstream should be called with "original_tool_name"
            mock_upstream.call_tool.assert_called_once_with(
                "original_tool_name", {"key": "value"}
            )


class TestToolNameAliasingInViews:
    """Tests for tool name aliasing in tool_views."""

    def test_view_alias_in_explicit_tools(self):
        """View with explicit tools should apply name alias."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"upstream_tool": ToolConfig(description="Original")},
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    tools={
                        "server": {
                            "upstream_tool": ToolConfig(
                                name="view_aliased_tool", description="View override"
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].name == "view_aliased_tool"
        assert tools[0].original_name == "upstream_tool"
        assert tools[0].description == "View override"

    def test_view_alias_in_include_all_mode(self):
        """View with include_all should apply alias from view overrides."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo", tools={"tool_a": ToolConfig(description="A")}
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                    tools={
                        "server": {
                            "tool_a": ToolConfig(
                                name="renamed_in_view", description="Renamed"
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].name == "renamed_in_view"
        assert tools[0].original_name == "tool_a"

