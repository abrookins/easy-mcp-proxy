"""Tests for ToolView with active client connections."""

from mcp_proxy.models import ToolConfig, ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolViewActiveClient:
    """Tests for ToolView with active client connections."""

    async def test_call_tool_uses_active_client(self):
        """call_tool should use active client when available."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server": {"my_tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Mock stored client (fallback)
        stored_client = AsyncMock()
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        # Mock active client (should be used)
        active_client = AsyncMock()
        active_client.call_tool = AsyncMock(return_value={"active": True})

        view._upstream_clients = {"server": stored_client}
        view._get_client = lambda s: active_client if s == "server" else None

        result = await view.call_tool("my_tool", {"arg": "value"})

        # Should use active client, not stored client
        active_client.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
        stored_client.call_tool.assert_not_called()
        assert result == {"active": True}

    async def test_upstream_tool_uses_active_client(self):
        """_call_upstream_tool should use active client when available."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server": {"tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Mock stored client
        stored_client = AsyncMock()
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        # Mock active client
        active_client = AsyncMock()
        active_client.call_tool = AsyncMock(return_value={"active": True})

        view._upstream_clients = {"server": stored_client}
        view._get_client = lambda s: active_client if s == "server" else None

        result = await view._call_upstream_tool("server.my_tool", query="test")

        # Should use active client
        active_client.call_tool.assert_called_once_with("my_tool", {"query": "test"})
        stored_client.call_tool.assert_not_called()
        assert result == {"active": True}

    async def test_call_tool_reconnects_on_failure(self):
        """call_tool should attempt reconnection when active client fails."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server": {"my_tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Track call count to fail first call, succeed on second
        call_count = 0

        async def mock_call_tool(name, args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection lost")
            return {"reconnected": True}

        active_client = AsyncMock()
        active_client.call_tool = mock_call_tool

        # Mock stored client (fallback)
        stored_client = AsyncMock()
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        view._upstream_clients = {"server": stored_client}
        view._get_client = lambda s: active_client if s == "server" else None
        view._reconnect_client = AsyncMock()

        result = await view.call_tool("my_tool", {"arg": "value"})

        # Should have called reconnect and then succeeded
        view._reconnect_client.assert_called_once_with("server")
        assert result == {"reconnected": True}
        assert call_count == 2

    async def test_call_tool_falls_back_to_fresh_client_after_reconnect_fails(self):
        """call_tool should fall back to fresh client if reconnect fails."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server": {"my_tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Active client always fails
        active_client = AsyncMock()
        active_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))

        # Stored client succeeds
        stored_client = AsyncMock()
        stored_client.call_tool = AsyncMock(return_value={"fallback": True})
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        view._upstream_clients = {"server": stored_client}
        view._get_client = lambda s: active_client if s == "server" else None
        # Reconnect succeeds but client still fails
        view._reconnect_client = AsyncMock()

        result = await view.call_tool("my_tool", {"arg": "value"})

        # Should have fallen back to stored client
        stored_client.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
        assert result == {"fallback": True}

    async def test_call_tool_raises_without_reconnect_callback(self):
        """call_tool should raise if active client fails and no reconnect callback."""
        from unittest.mock import AsyncMock

        import pytest

        config = ToolViewConfig(tools={"server": {"my_tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Active client fails
        active_client = AsyncMock()
        active_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))

        # Stored client (not used because we raise)
        stored_client = AsyncMock()
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        view._upstream_clients = {"server": stored_client}
        view._get_client = lambda s: active_client if s == "server" else None
        view._reconnect_client = None  # No reconnect callback

        with pytest.raises(Exception, match="Connection lost"):
            await view.call_tool("my_tool", {"arg": "value"})

    async def test_call_tool_fallback_when_reconnect_returns_no_client(self):
        """call_tool falls back to fresh client when reconnect leaves no client."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server": {"my_tool": ToolConfig()}})
        view = ToolView(name="test", config=config)

        # Active client fails once, then _get_client returns None after reconnect
        call_count = 0
        active_client = AsyncMock()
        active_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))

        def get_client(server_name):
            nonlocal call_count
            call_count += 1
            # First call returns active client, after reconnect returns None
            if call_count == 1:
                return active_client
            return None

        # Stored client succeeds
        stored_client = AsyncMock()
        stored_client.call_tool = AsyncMock(return_value={"fallback": True})
        stored_client.__aenter__ = AsyncMock(return_value=stored_client)
        stored_client.__aexit__ = AsyncMock()

        view._upstream_clients = {"server": stored_client}
        view._get_client = get_client
        view._reconnect_client = AsyncMock()

        result = await view.call_tool("my_tool", {"arg": "value"})

        # Should have fallen back to stored client
        stored_client.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
        assert result == {"fallback": True}
