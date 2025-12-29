"""Tests for MCPProxy error handling."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastmcp.client.transports import StdioTransport

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyErrorHandling:
    """Tests for MCPProxy error handling."""

    async def test_create_client_unknown_server_raises(self):
        """_create_client should raise for unknown server."""
        config = ProxyConfig(
            mcp_servers={"known": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="not found in config"):
            await proxy._create_client("unknown")

    def test_create_client_no_url_or_command_raises(self):
        """_create_client should raise if server has neither url nor command."""
        # Create a config where we manually break the server config
        config = ProxyConfig(
            mcp_servers={"broken": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Manually create a broken config for testing
        broken_config = UpstreamServerConfig(command=None, url=None)
        with pytest.raises(ValueError, match="must have either 'url' or 'command'"):
            proxy._create_client_from_config(broken_config)

    def test_create_client_from_config_with_cwd(self):
        """_create_client_from_config should pass cwd to StdioTransport."""
        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem", "/data"],
                    cwd="/data",
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a real StdioTransport mock that passes isinstance checks
        mock_transport_instance = MagicMock(spec=StdioTransport)

        with patch(
            "mcp_proxy.proxy.client.StdioTransport", return_value=mock_transport_instance
        ) as mock_transport_class:
            proxy._create_client_from_config(config.mcp_servers["fs"])

            # Verify cwd was passed to StdioTransport
            mock_transport_class.assert_called_once()
            call_kwargs = mock_transport_class.call_args
            assert call_kwargs.kwargs.get("cwd") == "/data"

    def test_create_client_from_config_cwd_with_env_expansion(self):
        """_create_client_from_config should expand env vars in cwd."""
        os.environ["TEST_CWD_PATH"] = "/expanded/path"

        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(command="echo", cwd="${TEST_CWD_PATH}")
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_transport_instance = MagicMock(spec=StdioTransport)

        with patch(
            "mcp_proxy.proxy.client.StdioTransport", return_value=mock_transport_instance
        ) as mock_transport_class:
            proxy._create_client_from_config(config.mcp_servers["fs"])

            call_kwargs = mock_transport_class.call_args
            cwd_value = call_kwargs.kwargs.get("cwd")
            assert cwd_value == "/expanded/path"

        del os.environ["TEST_CWD_PATH"]

    async def test_initialize_only_runs_once(self, sample_config_dict):
        """MCPProxy.initialize() should only run once."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        # First initialization
        await proxy.initialize()
        first_clients = dict(proxy.upstream_clients)

        # Second initialization should be a no-op
        await proxy.initialize()

        assert proxy.upstream_clients == first_clients

    async def test_call_upstream_tool_no_client_raises(self):
        """call_upstream_tool should raise if no client for server."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)
        # Don't call initialize - no clients registered

        with pytest.raises(ValueError, match="No client for server"):
            await proxy.call_upstream_tool("missing", "tool", {})

    def test_get_view_mcp_unknown_view_raises(self):
        """get_view_mcp should raise for unknown view."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="not found"):
            proxy.get_view_mcp("nonexistent")

    async def test_fetch_upstream_tools_no_client_raises(self):
        """fetch_upstream_tools should raise if no client for server."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)
        # Don't call initialize - no clients registered

        with pytest.raises(ValueError, match="No client for server"):
            await proxy.fetch_upstream_tools("missing")

    async def test_refresh_upstream_tools_with_clients(self):
        """refresh_upstream_tools should call fetch for all registered clients."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock the client
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = []
        proxy.upstream_clients = {"server": mock_client}

        await proxy.refresh_upstream_tools()

        mock_client.list_tools.assert_called()

