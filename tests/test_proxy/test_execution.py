"""Tests for running the proxy server and tool execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client

from mcp_proxy.models import OutputCacheConfig, ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy
from tests.helpers import get_required_tool


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

        registered_tool = await get_required_tool(view_mcp, "my_tool")

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

        registered_tool = await get_required_tool(view_mcp, "multi_tool")

        # Call the tool function with arguments dict
        result = await registered_tool.fn(arguments={"query": "test"})

        # The result should NOT be a stub message
        assert "message" not in result or "call via view.call_tool" not in str(
            result.get("message", "")
        )
        # Should have called upstream
        mock_client.call_tool.assert_called()

    async def test_registered_custom_tool_applies_output_protection(self, tmp_path):
        """Direct-mode custom tool registration should route through ToolView."""
        from mcp_proxy.custom_tools import custom_tool

        @custom_tool(name="custom_large", description="Large custom output")
        async def custom_large(size: int) -> dict:
            return {"payload": "x" * size}

        config = ProxyConfig(
            mcp_servers={},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {},
                }
            },
            output_cache=OutputCacheConfig(max_inline_chars=20, max_inline_tokens=100),
        )
        proxy = MCPProxy(config)
        proxy.views["view"].custom_tools["custom_large"] = custom_large
        proxy.views["view"]._cache_context = proxy._create_cache_context()

        view_mcp = proxy.get_view_mcp("view")
        registered_tool = await get_required_tool(view_mcp, "custom_large")

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            result = await registered_tool.fn(size=100)

        assert result.structured_content["cached"] is True
        assert result.structured_content["original"]["chars"] > 20


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

    @pytest.mark.asyncio
    async def test_default_mcp_large_output_is_protected(self, tmp_path):
        """Default root wrappers should protect large upstream outputs."""
        from fastmcp import FastMCP

        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={"my_tool": {"description": "A tool"}},
                )
            },
            tool_views={},
            output_cache=OutputCacheConfig(max_inline_chars=20, max_inline_tokens=100),
        )
        proxy = MCPProxy(config)

        mock_upstream = MagicMock()
        mock_upstream.call_tool = AsyncMock(return_value={"payload": "x" * 100})
        proxy._active_clients["server"] = mock_upstream

        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(
            test_mcp,
            [
                ToolInfo(
                    name="my_tool",
                    server="server",
                    original_name="my_tool",
                    input_schema={
                        "type": "object",
                        "properties": {"arg": {"type": "string"}},
                    },
                )
            ],
        )
        registered_tool = await get_required_tool(test_mcp, "my_tool")

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            result = await registered_tool.fn(arg="value")

        mock_upstream.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
        assert result.structured_content["cached"] is True
