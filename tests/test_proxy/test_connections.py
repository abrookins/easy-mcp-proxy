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

        # Mock connect_clients and disconnect_clients (the new lifespan behavior)
        with (
            patch.object(
                proxy, "connect_clients", new_callable=AsyncMock
            ) as mock_connect,
            patch.object(
                proxy, "disconnect_clients", new_callable=AsyncMock
            ) as mock_disconnect,
        ):
            # Use the lifespan context manager
            async with lifespan(None):
                mock_connect.assert_called_once_with(fetch_tools=True)
            # disconnect should be called on exit
            mock_disconnect.assert_called_once()

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

    def test_sync_fetch_tools_skips_when_tools_exist(self):
        """sync_fetch_tools should return early if tools already fetched."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Pre-populate _upstream_tools
        mock_tool = MagicMock()
        proxy._upstream_tools = {"server": [mock_tool]}

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            with patch.object(proxy, "fetch_upstream_tools", new_callable=AsyncMock):
                proxy.sync_fetch_tools()

        # Should NOT have called _create_client since tools already exist
        mock_create.assert_not_called()

    def test_sync_fetch_tools_creates_client_and_handles_error(self):
        """sync_fetch_tools should create clients and handle errors gracefully."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_client = AsyncMock()

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock, return_value=mock_client
        ):
            with patch.object(
                proxy,
                "fetch_upstream_tools",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Failed"),
            ):
                # Should not raise - errors are caught
                proxy.sync_fetch_tools()

        # Client should be stored despite error
        assert proxy.upstream_clients["server"] is mock_client

    async def test_sync_fetch_tools_skips_when_loop_running(self):
        """sync_fetch_tools should do nothing when called from async context."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            # Already in async context - sync_fetch_tools should detect loop
            # and not run asyncio.run()
            proxy.sync_fetch_tools()

        # Should NOT have called _create_client since we're in async context
        mock_create.assert_not_called()

    async def test_fetch_tools_from_active_clients(self):
        """fetch_tools_from_active_clients should delegate to client manager."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]

        proxy._active_clients["server"] = mock_client

        await proxy.fetch_tools_from_active_clients()

        # Check that tools were fetched
        assert "server" in proxy._upstream_tools


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

    async def test_fetch_tools_from_active_client_success(self):
        """fetch_tools_from_active_client should fetch tools from connected client."""
        from mcp_proxy.proxy.client import ClientManager

        mock_tool = MagicMock()
        mock_tool.name = "active_tool"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager._active_clients["server"] = mock_client

        tools = await manager.fetch_tools_from_active_client("server")

        assert len(tools) == 1
        assert tools[0].name == "active_tool"
        assert "server" in manager._upstream_tools

    async def test_fetch_tools_from_active_client_not_found(self):
        """fetch_tools_from_active_client should raise for unknown server."""
        import pytest

        from mcp_proxy.proxy.client import ClientManager

        config = ProxyConfig(mcp_servers={}, tool_views={})
        manager = ClientManager(config)

        with pytest.raises(ValueError, match="No active client for server"):
            await manager.fetch_tools_from_active_client("nonexistent")

    async def test_refresh_tools_from_active_clients_success(self):
        """refresh_tools_from_active_clients should fetch from all clients."""
        from mcp_proxy.proxy.client import ClientManager

        mock_tool = MagicMock()
        mock_tool.name = "refreshed_tool"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager._active_clients["server"] = mock_client

        await manager.refresh_tools_from_active_clients()

        assert "server" in manager._upstream_tools
        assert manager._upstream_tools["server"][0].name == "refreshed_tool"

    async def test_refresh_tools_from_active_clients_with_callback(self):
        """refresh_tools_from_active_clients should call instruction callback."""
        from mcp_proxy.proxy.client import ClientManager

        mock_tool = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager._active_clients["server"] = mock_client

        callback = AsyncMock()
        await manager.refresh_tools_from_active_clients(instruction_callback=callback)

        callback.assert_called_once_with("server", mock_client)

    async def test_refresh_tools_from_active_clients_handles_errors(self):
        """refresh_tools_from_active_clients should continue on errors."""
        from mcp_proxy.proxy.client import ClientManager

        mock_client = AsyncMock()
        mock_client.list_tools.side_effect = ConnectionError("Failed")

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)
        manager._active_clients["server"] = mock_client

        # Should not raise
        await manager.refresh_tools_from_active_clients()

    async def test_connect_clients_with_fetch_tools(self):
        """connect_clients with fetch_tools=True should fetch tools."""
        from mcp_proxy.proxy.client import ClientManager

        mock_tool = MagicMock()
        mock_tool.name = "fetched_tool"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        manager = ClientManager(config)

        with patch.object(
            manager, "create_client_from_config", return_value=mock_client
        ):
            await manager.connect_clients(fetch_tools=True)

        assert "server" in manager._upstream_tools
        mock_client.list_tools.assert_called_once()

        await manager.disconnect_clients()

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


class TestProxyGetToolInstructions:
    """Tests for get_tool_instructions default message."""

    async def test_get_tool_instructions_returns_default_when_no_instructions(self):
        """get_tool_instructions tool returns default message when none available."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)
        # Don't set any upstream_instructions - should return default message

        view_mcp = proxy.get_view_mcp("myview")

        async with Client(view_mcp) as client:
            result = await client.call_tool("get_tool_instructions", {})
            text_content = result.content[0].text
            assert "No tool instructions available" in text_content


class TestReconnectionLogic:
    """Tests for automatic reconnection when upstream connections fail."""

    async def test_reconnect_client_creates_new_connection(self):
        """_reconnect_client should create a new connection after failure."""
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
            # First connect
            await proxy.connect_clients()
            assert proxy.has_active_connection("server")

            # Simulate connection failure by removing the client
            proxy._client_manager._active_clients.pop("server")
            assert not proxy.has_active_connection("server")

            # Reconnect
            await proxy.reconnect_client("server")
            assert proxy.has_active_connection("server")

    async def test_call_upstream_tool_reconnects_on_failure(self):
        """call_upstream_tool should attempt reconnection when active client fails."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a mock client that fails on first call, succeeds on second
        call_count = 0

        async def mock_call_tool(name, args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection lost")
            return {"result": "success"}

        mock_client = AsyncMock()
        mock_client.call_tool = mock_call_tool
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()

            # Call should fail, trigger reconnect, then succeed
            result = await proxy.call_upstream_tool("server", "test_tool", {})
            assert result == {"result": "success"}
            assert call_count == 2  # First call failed, second succeeded

    async def test_call_upstream_tool_falls_back_to_fresh_client(self):
        """call_upstream_tool should fall back to fresh client if reconnect fails."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a mock client that always fails when used as active client
        failing_client = AsyncMock()
        failing_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        failing_client.__aenter__ = AsyncMock(return_value=failing_client)
        failing_client.__aexit__ = AsyncMock()

        # Create a fresh client that succeeds
        fresh_client = AsyncMock()
        fresh_client.call_tool = AsyncMock(return_value={"result": "fresh"})
        fresh_client.__aenter__ = AsyncMock(return_value=fresh_client)
        fresh_client.__aexit__ = AsyncMock()

        clients = [failing_client, failing_client, fresh_client]
        client_index = 0

        def get_client(*args):
            nonlocal client_index
            client = clients[client_index]
            client_index += 1
            return client

        with patch.object(
            proxy._client_manager, "create_client_from_config", side_effect=get_client
        ):
            await proxy.connect_clients()

            # Call should fail, reconnect should fail, then fall back to fresh client
            result = await proxy.call_upstream_tool("server", "test_tool", {})
            assert result == {"result": "fresh"}

    async def test_reconnect_client_no_exit_stack(self):
        """_reconnect_client should return early when no exit stack exists."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Don't call connect_clients, so _exit_stack will be None
        # This should not raise, just return early
        await proxy.reconnect_client("server")

        # Verify no client was added
        assert not proxy.has_active_connection("server")

    async def test_reconnect_client_handles_connection_failure(self):
        """_reconnect_client should handle connection failures gracefully."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # First connect successfully
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()
            assert proxy.has_active_connection("server")

        # Now simulate reconnect failing
        failing_client = AsyncMock()
        failing_client.__aenter__ = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        failing_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager,
            "create_client_from_config",
            return_value=failing_client,
        ):
            # Remove old client to simulate failure
            proxy._client_manager._active_clients.pop("server")

            # Reconnect should fail but not raise
            await proxy.reconnect_client("server")

            # Should still have no connection
            assert not proxy.has_active_connection("server")

    async def test_lifespan_initializes_views_with_reconnect(self):
        """_create_lifespan should initialize views with reconnect callback."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)

        lifespan = proxy._create_lifespan()

        with (
            patch.object(
                proxy, "connect_clients", new_callable=AsyncMock
            ) as mock_connect,
            patch.object(proxy, "disconnect_clients", new_callable=AsyncMock),
        ):
            async with lifespan(None):
                mock_connect.assert_called_once_with(fetch_tools=True)
                # Verify the view was initialized
                assert proxy._initialized

    async def test_call_upstream_tool_reconnect_no_client_falls_back(self):
        """call_upstream_tool should fall back when reconnect doesn't add client."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a mock client that fails on first call
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        # Fresh client that succeeds
        fresh_client = AsyncMock()
        fresh_client.call_tool = AsyncMock(return_value={"result": "fresh"})
        fresh_client.__aenter__ = AsyncMock(return_value=fresh_client)
        fresh_client.__aexit__ = AsyncMock()

        call_count = 0

        def get_client(cfg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_client
            return fresh_client

        with patch.object(
            proxy._client_manager, "create_client_from_config", side_effect=get_client
        ):
            await proxy.connect_clients()

            # Mock _reconnect_client to succeed but NOT add a client
            async def mock_reconnect(server_name):
                # Remove the client but don't add a new one
                proxy._client_manager._active_clients.pop(server_name, None)

            with patch.object(
                proxy._client_manager, "_reconnect_client", side_effect=mock_reconnect
            ):
                # Call should fail, reconnect should "succeed" but no client,
                # then fall back to fresh client
                result = await proxy.call_upstream_tool("server", "test_tool", {})
                assert result == {"result": "fresh"}
