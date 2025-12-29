"""End-to-end tests for HTTP server with MCP protocol.

These tests use FastMCP's run_server_async to actually run the server
and connect to it with MCP client.
"""

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async


class TestHTTPServerIntegration:
    """End-to-end tests for HTTP server with MCP protocol."""

    @pytest.mark.asyncio
    async def test_http_server_lists_tools(self):
        """HTTP server should list tools via MCP protocol."""
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
            async with Client(transport=StreamableHttpTransport(url)) as client:
                tools = await client.list_tools()
                assert len(tools) == 2
                tool_names = [t.name for t in tools]
                assert "tool_one" in tool_names
                assert "tool_two" in tool_names
