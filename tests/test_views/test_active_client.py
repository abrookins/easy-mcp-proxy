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

