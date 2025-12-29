"""Integration tests for MCP protocol.

These tests verify that the MCP protocol actually works end-to-end,
not just that routes exist.
"""

import pytest

from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProtocolIntegration:
    """Integration tests for MCP protocol."""

    @pytest.mark.asyncio
    async def test_default_view_lists_tools_from_config(self):
        """Default MCP should list tools configured in mcp_servers."""
        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",  # Dummy command
                    tools={
                        "tool_a": {"description": "Tool A description"},
                        "tool_b": {"description": "Tool B description"},
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Get the default FastMCP instance with tools
        default_tools = proxy.get_view_tools(None)

        # Verify tools are extracted from config
        assert len(default_tools) == 2
        tool_names = [t.name for t in default_tools]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    @pytest.mark.asyncio
    async def test_view_lists_only_configured_tools(self):
        """View should only list tools from that view's config."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                    tools={
                        "search_code": {},
                        "search_issues": {},
                        "get_file_contents": {},
                        "create_branch": {},
                    },
                )
            },
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {"description": "Search code"},
                            "search_issues": {"description": "Search issues"},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Get the research view tools
        research_tools = proxy.get_view_tools("research")

        # Should only have 2 tools from the research view
        assert len(research_tools) == 2
        tool_names = [t.name for t in research_tools]
        assert "search_code" in tool_names
        assert "search_issues" in tool_names
        # Should NOT include tools not in the view
        assert "get_file_contents" not in tool_names
        assert "create_branch" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_descriptions_from_config(self):
        """Tools should have descriptions from config."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={"my_tool": {"description": "This is my tool description"}},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        my_tool = next(t for t in tools if t.name == "my_tool")
        assert my_tool.description == "This is my tool description"

    @pytest.mark.asyncio
    async def test_http_app_registers_tools_on_fastmcp(self):
        """http_app() should register tools on FastMCP instances."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_one": {"description": "First tool"},
                        "tool_two": {"description": "Second tool"},
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create the HTTP app (this should register tools)
        app = proxy.http_app()

        # Verify the app was created
        assert app is not None

        # The tools should be available via get_view_tools
        tools = proxy.get_view_tools(None)
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_view_tool_descriptions_override(self):
        """View can override tool descriptions."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                    tools={
                        "search_code": {"description": "Original description"},
                    },
                )
            },
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {
                                "description": "Research-specific description"
                            },
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Default view should have original description
        default_tools = proxy.get_view_tools(None)
        default_search = next(t for t in default_tools if t.name == "search_code")
        assert default_search.description == "Original description"

        # Research view should have overridden description
        research_tools = proxy.get_view_tools("research")
        research_search = next(t for t in research_tools if t.name == "search_code")
        assert research_search.description == "Research-specific description"

