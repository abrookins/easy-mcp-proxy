"""Integration tests using FastMCP Client to test actual MCP protocol."""

import pytest
from fastmcp import Client, FastMCP
from mcp import types
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_proxy.cache import (
    create_cache_routes,
    create_cached_output_with_meta,
    retrieve_by_token,
)
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

    @pytest.mark.asyncio
    async def test_tool_can_return_mcp_and_signed_http_resource_links(self, tmp_path):
        """A tool can return multiple resource links for the same cached output."""
        import json
        from unittest.mock import patch

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            cached = create_cached_output_with_meta(
                content='{"large":"payload"}',
                secret="test-secret",
                base_url="http://testserver",
                ttl_seconds=3600,
                preview_chars=8,
            )

            mcp = FastMCP("Dual Link Test")

            @mcp.resource(
                "mcp://easy-mcp-proxy/cache/{token}",
                name="cached-output",
                mime_type="application/json",
            )
            def cached_output_resource(token: str) -> dict:
                content = retrieve_by_token(token, "test-secret")
                assert content is not None
                return json.loads(content)

            @mcp.tool(name="get_cached_output_links")
            def get_cached_output_links() -> list[types.ContentBlock]:
                return [
                    types.TextContent(type="text", text=cached.preview),
                    types.ResourceLink(
                        type="resource_link",
                        name="cached-output-mcp",
                        title="Cached output via MCP",
                        uri=f"mcp://easy-mcp-proxy/cache/{cached.token}",
                        description="Canonical MCP resource URI",
                        mimeType="application/json",
                        size=cached.size_bytes,
                    ),
                    types.ResourceLink(
                        type="resource_link",
                        name="cached-output-http",
                        title="Cached output via HTTPS",
                        uri=cached.retrieve_url,
                        description="Signed HTTP retrieval URL",
                        mimeType="application/json",
                        size=cached.size_bytes,
                        _meta={"access": "signed_http"},
                    ),
                ]

            async with Client(mcp) as client:
                result = await client.call_tool("get_cached_output_links", {})

                assert len(result.content) == 3
                assert result.content[0].type == "text"

                mcp_link = next(
                    block
                    for block in result.content
                    if getattr(block, "name", "") == "cached-output-mcp"
                )
                http_link = next(
                    block
                    for block in result.content
                    if getattr(block, "name", "") == "cached-output-http"
                )

                assert mcp_link.type == "resource_link"
                assert str(mcp_link.uri) == f"mcp://easy-mcp-proxy/cache/{cached.token}"
                assert http_link.type == "resource_link"
                assert str(http_link.uri) == cached.retrieve_url
                assert http_link.meta == {"access": "signed_http"}

                resource_contents = await client.read_resource(mcp_link.uri)
                assert len(resource_contents) == 1
                assert resource_contents[0].mimeType == "application/json"
                assert json.loads(resource_contents[0].text) == {"large": "payload"}

            http_app = Starlette(routes=create_cache_routes("test-secret"))
            http_client = TestClient(http_app)
            http_response = http_client.get(cached.retrieve_url)

            assert http_response.status_code == 200
            assert http_response.text == '{"large":"payload"}'
