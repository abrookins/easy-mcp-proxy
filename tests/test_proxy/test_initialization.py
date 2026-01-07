"""Tests for MCPProxy initialization and client creation."""

from unittest.mock import AsyncMock, patch

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyInitialization:
    """Tests for MCPProxy initialization."""

    def test_proxy_creation_from_config(self, sample_config_dict):
        """MCPProxy should be creatable from config dict."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy is not None
        assert len(proxy.views) == 1

    def test_proxy_has_fastmcp_server(self, sample_config_dict):
        """MCPProxy should have a FastMCP server instance."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy.server is not None
        assert proxy.server.name == "MCP Tool View Proxy"

    async def test_proxy_initialize_connects_upstreams(self, sample_config_dict):
        """MCPProxy.initialize() should register clients for all servers."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        # Mock client creation and tool refresh to avoid actual connections
        mock_client = AsyncMock()
        with patch.object(proxy, "_create_client", return_value=mock_client):
            with patch.object(proxy, "refresh_upstream_tools", new_callable=AsyncMock):
                await proxy.initialize()

        # Should have clients registered for all servers in config
        assert "test-server" in proxy.upstream_clients


class TestMCPProxyClientCreation:
    """Tests for upstream client creation."""

    async def test_create_client_for_command_server(self):
        """_create_client should handle command-based servers."""
        config = ProxyConfig(
            mcp_servers={"test": UpstreamServerConfig(command="echo", args=["test"])},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Client creation should succeed (actual connection happens on use)
        client = await proxy._create_client("test")
        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")

    async def test_create_client_for_url_server(self):
        """_create_client should handle URL-based servers."""
        config = ProxyConfig(
            mcp_servers={"test": UpstreamServerConfig(url="http://localhost:8080/mcp")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Client creation should succeed
        client = await proxy._create_client("test")
        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")
