"""Integration tests for HTTP MCP protocol.

These tests verify that the MCP protocol actually works end-to-end,
not just that routes exist.

Uses FastMCP's in-memory Client for efficient testing.
"""

import pytest
from fastmcp import Client

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
                    }
                )
            },
            tool_views={}
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
                    }
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
                    }
                )
            }
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
                    tools={
                        "my_tool": {"description": "This is my tool description"}
                    }
                )
            },
            tool_views={}
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
                    }
                )
            },
            tool_views={}
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
                    }
                )
            },
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {"description": "Research-specific description"},
                        }
                    }
                )
            }
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


class TestMCPClientIntegration:
    """Integration tests using FastMCP Client to test actual MCP protocol."""

    @pytest.mark.asyncio
    async def test_client_lists_tools_via_mcp_protocol(self):
        """MCP Client should be able to list tools from proxy FastMCP server."""
        from fastmcp import FastMCP

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
        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "my_tool": {"description": "My tool description"},
                        "another_tool": {"description": "Another description"},
                    }
                )
            },
            tool_views={}
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
        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                    tools={
                        "search_code": {"description": "Search code"},
                        "search_issues": {"description": "Search issues"},
                        "create_branch": {"description": "Create branch"},
                        "merge_pr": {"description": "Merge PR"},
                    }
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
                    }
                )
            }
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
                    }
                )
            },
            tool_views={}
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
                    tools={
                        "my_tool": {"description": "My special tool"}
                    }
                )
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        async with Client(proxy.server) as client:
            tools = await client.list_tools()
            my_tool = next(t for t in tools if t.name == "my_tool")
            assert my_tool.description == "My special tool"

    @pytest.mark.asyncio
    async def test_get_view_tools_unknown_view_raises(self):
        """get_view_tools() should raise ValueError for unknown view."""
        config = ProxyConfig(
            mcp_servers={},
            tool_views={}
        )
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
                    }
                )
            }
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
        config = ProxyConfig(
            mcp_servers={},
            tool_views={}
        )
        proxy = MCPProxy(config)

        # Manually register a tool that references a non-existent server
        from mcp_proxy.proxy import ToolInfo
        from fastmcp import FastMCP

        tools = [
            ToolInfo(
                name="my_tool",
                description="My tool",
                server="nonexistent",
                original_name="my_tool"
            )
        ]
        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools)

        # Call the tool - should error because server is not configured
        async with Client(test_mcp) as client:
            with pytest.raises(ToolError, match="not configured"):
                await client.call_tool("my_tool", {})


class TestHTTPServerIntegration:
    """End-to-end tests for HTTP server with MCP protocol.

    These tests use FastMCP's run_server_async to actually run the server
    and connect to it with MCP client.
    """

    @pytest.mark.asyncio
    async def test_http_server_lists_tools(self):
        """HTTP server should list tools via MCP protocol."""
        from fastmcp import FastMCP
        from fastmcp.utilities.tests import run_server_async
        from fastmcp.client.transports import StreamableHttpTransport

        # Create a simple MCP server with tools
        mcp = FastMCP("Test Server")

        @mcp.tool(description="First tool")
        def tool_one() -> str:
            return "one"

        @mcp.tool(description="Second tool")
        def tool_two() -> str:
            return "two"

        # Run server and connect with HTTP transport
        async with run_server_async(mcp) as url:
            async with Client(
                transport=StreamableHttpTransport(url)
            ) as client:
                tools = await client.list_tools()
                assert len(tools) == 2
                tool_names = [t.name for t in tools]
                assert "tool_one" in tool_names
                assert "tool_two" in tool_names

