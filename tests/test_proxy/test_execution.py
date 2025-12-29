"""Tests for running the proxy server and tool execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyRun:
    """Tests for running the proxy server."""

    async def test_run_with_stdio_transport(self):
        """MCPProxy.run() should support stdio transport."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # Would need to mock FastMCP.run()
        # This verifies the interface exists
        assert hasattr(proxy, "run")

    async def test_run_with_http_transport(self):
        """MCPProxy.run() should support HTTP transport."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # run() should accept transport and port parameters
        assert hasattr(proxy, "run")


class TestMCPProxyToolExecution:
    """Tests for tool execution - tools should route to upstream, not return stubs."""

    async def test_registered_tool_executes_upstream(self):
        """Tools registered on MCP should execute upstream tools, not return stubs."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"my_tool": {"description": "A tool"}}},
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "from_upstream"}
        proxy.upstream_clients = {"server": mock_client}
        # Also inject into the view
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP
        view_mcp = proxy.get_view_mcp("view")

        # Find the registered tool
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "my_tool":
                registered_tool = tool
                break

        assert registered_tool is not None, "Tool should be registered"

        # Call the tool function with arguments dict (FastMCP doesn't support **kwargs)
        result = await registered_tool.fn(arguments={"arg": "value"})

        # Should call upstream and return result
        mock_client.call_tool.assert_called_once()
        assert result == {"result": "from_upstream"}

    async def test_registered_composite_tool_executes(self):
        """Composite tools registered on MCP should execute, not return stubs."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {},
                    "composite_tools": {
                        "multi_tool": {
                            "description": "Composite tool",
                            "inputs": {"query": {"type": "string"}},
                            "parallel": {
                                "result": {
                                    "tool": "server.tool_a",
                                    "args": {"q": "{inputs.query}"},
                                }
                            },
                        }
                    },
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "from_upstream"}
        proxy.upstream_clients = {"server": mock_client}
        # Also inject into the view
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP
        view_mcp = proxy.get_view_mcp("view")

        # Find the registered composite tool
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "multi_tool":
                registered_tool = tool
                break

        assert registered_tool is not None, "Composite tool should be registered"

        # Call the tool function with arguments dict
        result = await registered_tool.fn(arguments={"query": "test"})

        # The result should NOT be a stub message
        assert "message" not in result or "call via view.call_tool" not in str(
            result.get("message", "")
        )
        # Should have called upstream
        mock_client.call_tool.assert_called()


class TestDefaultMCPUpstreamCalls:
    """Tests for default MCP (no view) upstream tool calls."""

    @pytest.mark.asyncio
    async def test_default_mcp_calls_upstream_when_connected(self):
        """Default MCP tools should call upstream when clients are connected."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={"my_tool": {"description": "A tool"}},
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
            # Call through the proxy's default server
            # Tools use "arguments" dict parameter per FastMCP convention
            async with Client(proxy.server) as client:
                await client.call_tool("my_tool", {"arguments": {"arg": "value"}})

            # Verify upstream was called with the arguments dict
            mock_upstream.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
