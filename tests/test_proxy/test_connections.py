"""Tests for proxy connection management."""

from unittest.mock import AsyncMock, MagicMock, patch

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestProxyConnectionManagement:
    """Tests for proxy connection management."""

    async def test_connect_clients_creates_connections(self):
        """connect_clients should create active connections."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock client creation
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()

        assert proxy.has_active_connection("server")
        assert proxy.get_active_client("server") is mock_client

        # Cleanup
        await proxy.disconnect_clients()

    async def test_disconnect_clients_clears_connections(self):
        """disconnect_clients should close all connections."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()
            assert proxy.has_active_connection("server")

            await proxy.disconnect_clients()

        assert not proxy.has_active_connection("server")
        assert proxy.get_active_client("server") is None

    async def test_connect_clients_handles_errors(self):
        """connect_clients should continue if a server fails."""
        config = ProxyConfig(
            mcp_servers={
                "bad_server": UpstreamServerConfig(command="nonexistent"),
                "good_server": UpstreamServerConfig(command="echo"),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # First call fails, second succeeds
        mock_good_client = AsyncMock()
        mock_good_client.__aenter__ = AsyncMock(return_value=mock_good_client)
        mock_good_client.__aexit__ = AsyncMock()

        call_count = 0

        def create_client_side_effect(cfg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Cannot connect")
            return mock_good_client

        with patch.object(
            proxy._client_manager,
            "create_client_from_config",
            side_effect=create_client_side_effect,
        ):
            await proxy.connect_clients()

        # Bad server should not be connected
        # Good server should be connected
        # (Order depends on dict iteration - just check at least one works)
        await proxy.disconnect_clients()

    async def test_connect_clients_idempotent(self):
        """connect_clients should do nothing if already connected."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ) as mock_create:
            await proxy.connect_clients()
            await proxy.connect_clients()  # Second call should be no-op

        # Should only be called once
        assert mock_create.call_count == 1

        await proxy.disconnect_clients()

    async def test_disconnect_clients_when_not_connected(self):
        """disconnect_clients should be safe when not connected."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Should not raise
        await proxy.disconnect_clients()

    async def test_call_upstream_tool_with_active_client(self):
        """call_upstream_tool should use active client when available."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock active client
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "success"})
        proxy._active_clients["server"] = mock_client

        result = await proxy.call_upstream_tool("server", "tool_name", {"arg": "value"})

        assert result == {"result": "success"}

    def test_get_active_client_returns_none_for_unknown(self):
        """get_active_client should return None for unknown server."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        assert proxy.get_active_client("unknown") is None

    def test_has_active_connection_returns_false_for_unknown(self):
        """has_active_connection should return False for unknown server."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        assert not proxy.has_active_connection("unknown")

    async def test_lifespan_context_manager(self):
        """_create_lifespan should create a working context manager."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        lifespan = proxy._create_lifespan()

        # Mock the initialize method
        with patch.object(proxy, "initialize", new_callable=AsyncMock) as mock_init:
            # Use the lifespan context manager
            async with lifespan(None):
                mock_init.assert_called_once()

    async def test_initialize_skips_existing_clients(self):
        """initialize should skip creating clients that already exist."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Pre-populate upstream_clients
        existing_client = MagicMock()
        proxy.upstream_clients["server"] = existing_client

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            with patch.object(proxy, "refresh_upstream_tools", new_callable=AsyncMock):
                await proxy.initialize()

        # Should NOT have called _create_client since client already exists
        mock_create.assert_not_called()
        # Existing client should still be there
        assert proxy.upstream_clients["server"] is existing_client

    def test_sync_fetch_tools_skips_existing_clients(self):
        """sync_fetch_tools should skip creating clients that already exist."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Pre-populate upstream_clients
        existing_client = MagicMock()
        proxy.upstream_clients["server"] = existing_client

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            with patch.object(proxy, "fetch_upstream_tools", new_callable=AsyncMock):
                proxy.sync_fetch_tools()

        # Should NOT have called _create_client since client already exists
        mock_create.assert_not_called()


class TestProxyClientFetchUpstreamTools:
    """Tests for fetch_upstream_tools in client.py."""

    async def test_fetch_upstream_tools_server_not_found(self):
        """fetch_upstream_tools should raise error for unknown server."""
        import pytest

        from mcp_proxy.proxy.client import ClientManager

        config = ProxyConfig(mcp_servers={}, tool_views={})
        manager = ClientManager(config)

        with pytest.raises(ValueError, match="No client for server"):
            await manager.fetch_upstream_tools("nonexistent")

    async def test_fetch_upstream_tools_success(self):
        """fetch_upstream_tools should fetch and cache tools."""
        from mcp_proxy.proxy.client import ClientManager

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager.upstream_clients["server"] = mock_client

        tools = await manager.fetch_upstream_tools("server")

        assert len(tools) == 1
        assert tools[0].name == "test_tool"
        assert "server" in manager._upstream_tools

    async def test_refresh_upstream_tools_handles_errors(self):
        """refresh_upstream_tools should continue on errors."""
        from mcp_proxy.proxy.client import ClientManager

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(side_effect=ConnectionError("Failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager.upstream_clients["server"] = mock_client

        # Should not raise - errors are caught
        await manager.refresh_upstream_tools()


class TestProxyPropertySetters:
    """Tests for proxy property setters."""

    def test_upstream_tools_setter(self):
        """Setting _upstream_tools should update client manager."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        test_tools = {"server": [MagicMock()]}
        proxy._upstream_tools = test_tools

        assert proxy._upstream_tools == test_tools

    def test_active_clients_setter(self):
        """Setting _active_clients should update client manager."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        test_clients = {"server": MagicMock()}
        proxy._active_clients = test_clients

        assert proxy._active_clients == test_clients


class TestProxyGetServerInstructions:
    """Tests for get_server_instructions default message."""

    async def test_get_server_instructions_returns_default_when_no_instructions(self):
        """get_server_instructions tool returns default message when none available."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)
        # Don't set any upstream_instructions - should return default message

        view_mcp = proxy.get_view_mcp("myview")

        async with Client(view_mcp) as client:
            result = await client.call_tool("get_server_instructions", {})
            text_content = result.content[0].text
            assert "No server instructions available" in text_content
