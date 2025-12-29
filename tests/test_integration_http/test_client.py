"""Integration tests using FastMCP Client to test actual MCP protocol."""

import pytest
from fastmcp import Client, FastMCP

from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPClientIntegration:
    """Integration tests using FastMCP Client to test actual MCP protocol."""

    @pytest.mark.asyncio
    async def test_client_lists_tools_via_mcp_protocol(self):
        """MCP Client should be able to list tools from proxy FastMCP server."""
        # Create a FastMCP server with tools (simulating what http_app creates)
        mcp = FastMCP("Test Server")

        @mcp.tool(description="First tool")
        def tool_one() -> str:
            return "one"

        @mcp.tool(description="Second tool")
        def tool_two() -> str:
            return "two"

        # Use in-memory client to test MCP protocol
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 2
            tool_names = [t.name for t in tools]
            assert "tool_one" in tool_names
            assert "tool_two" in tool_names

    @pytest.mark.asyncio
    async def test_proxy_fastmcp_registers_tools_correctly(self):
        """Verify MCPProxy._register_tools_on_mcp() registers tools properly."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "my_tool": {"description": "My tool description"},
                        "another_tool": {"description": "Another description"},
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a FastMCP and register tools
        mcp = FastMCP("Test")
        tools = proxy.get_view_tools(None)
        proxy._register_tools_on_mcp(mcp, tools)

        # Use in-memory client to verify tools are registered
        async with Client(mcp) as client:
            listed_tools = await client.list_tools()
            assert len(listed_tools) == 2

            tool_names = [t.name for t in listed_tools]
            assert "my_tool" in tool_names
            assert "another_tool" in tool_names

            # Check descriptions
            my_tool = next(t for t in listed_tools if t.name == "my_tool")
            assert my_tool.description == "My tool description"

    @pytest.mark.asyncio
    async def test_view_fastmcp_has_only_view_tools(self):
        """View FastMCP instance should only have view-specific tools."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                    tools={
                        "search_code": {"description": "Search code"},
                        "search_issues": {"description": "Search issues"},
                        "create_branch": {"description": "Create branch"},
                        "merge_pr": {"description": "Merge PR"},
                    },
                )
            },
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {},
                            "search_issues": {},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Create view FastMCP and register view-specific tools
        view_mcp = FastMCP("Research View")
        view_tools = proxy.get_view_tools("research")
        proxy._register_tools_on_mcp(view_mcp, view_tools)

        # Use in-memory client to verify only view tools are present
        async with Client(view_mcp) as client:
            listed_tools = await client.list_tools()
            assert len(listed_tools) == 2

            tool_names = [t.name for t in listed_tools]
            assert "search_code" in tool_names
            assert "search_issues" in tool_names
            # These should NOT be present
            assert "create_branch" not in tool_names
            assert "merge_pr" not in tool_names
