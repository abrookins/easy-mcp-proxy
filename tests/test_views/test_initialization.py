"""Tests for ToolView initialization."""

import pytest

from mcp_proxy.hooks import HookResult
from mcp_proxy.models import HooksConfig, ToolConfig, ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolViewInitialization:
    """Tests for ToolView initialization."""

    async def test_tool_view_creation(self):
        """ToolView should be creatable with a name and config."""
        config = ToolViewConfig(description="Test view")
        view = ToolView(name="test-view", config=config)

        assert view.name == "test-view"
        assert view.description == "Test view"

    def test_tool_view_skips_custom_tools_without_module(self):
        """ToolView should skip custom_tools entries without 'module' key."""
        config = ToolViewConfig(
            description="Test view",
            custom_tools=[
                {"not_module": "value"},  # Missing 'module' key - should be skipped
            ],
        )
        view = ToolView(name="test", config=config)

        # No custom tools should be loaded since none have 'module'
        assert len(view.custom_tools) == 0

    async def test_tool_view_initialize_loads_tools(self):
        """ToolView.initialize() should load tools from upstream servers."""
        config = ToolViewConfig(
            tools={"upstream-server": {"tool_a": ToolConfig(), "tool_b": ToolConfig()}}
        )
        view = ToolView(name="test", config=config)

        # Mock upstream connections would be needed here
        # This test verifies the interface exists
        with pytest.raises(ValueError, match="Missing client for server"):
            await view.initialize(upstream_clients={})

    async def test_tool_view_initialize_with_valid_clients(self):
        """ToolView.initialize() should work with matching clients."""
        config = ToolViewConfig(
            tools={
                "server-a": {
                    "tool_a": ToolConfig(),
                }
            }
        )
        view = ToolView(name="test", config=config)

        # Mock client
        mock_client = object()

        # Should not raise when client is provided
        await view.initialize(upstream_clients={"server-a": mock_client})
        assert view._upstream_clients == {"server-a": mock_client}

    async def test_tool_view_initialize_loads_hooks(self):
        """ToolView.initialize() should load hooks from dotted paths."""
        import sys
        from unittest.mock import MagicMock

        # Create a mock module with hook functions
        mock_hooks = MagicMock()
        mock_hooks.pre_call = lambda args, ctx: None
        mock_hooks.post_call = lambda result, args, ctx: None
        sys.modules["test_hooks_module"] = mock_hooks

        try:
            config = ToolViewConfig(
                hooks=HooksConfig(
                    pre_call="test_hooks_module.pre_call",
                    post_call="test_hooks_module.post_call",
                )
            )
            view = ToolView(name="test", config=config)
            await view.initialize(upstream_clients={})

            # Hooks should be loaded
            assert view._pre_call_hook is not None
            assert view._post_call_hook is not None
        finally:
            del sys.modules["test_hooks_module"]

    async def test_tool_view_initialize_loads_pre_call_only(self):
        """ToolView.initialize() should work with only pre_call hook."""
        import sys
        from unittest.mock import MagicMock

        mock_hooks = MagicMock()
        mock_hooks.pre_call = lambda args, ctx: None
        sys.modules["test_hooks_pre_only"] = mock_hooks

        try:
            config = ToolViewConfig(
                hooks=HooksConfig(
                    pre_call="test_hooks_pre_only.pre_call", post_call=None
                )
            )
            view = ToolView(name="test", config=config)
            await view.initialize(upstream_clients={})

            assert view._pre_call_hook is not None
            assert view._post_call_hook is None
        finally:
            del sys.modules["test_hooks_pre_only"]

    async def test_tool_view_initialize_loads_post_call_only(self):
        """ToolView.initialize() should work with only post_call hook."""
        import sys
        from unittest.mock import MagicMock

        mock_hooks = MagicMock()
        mock_hooks.post_call = lambda result, args, ctx: None
        sys.modules["test_hooks_post_only"] = mock_hooks

        try:
            config = ToolViewConfig(
                hooks=HooksConfig(
                    pre_call=None, post_call="test_hooks_post_only.post_call"
                )
            )
            view = ToolView(name="test", config=config)
            await view.initialize(upstream_clients={})

            assert view._pre_call_hook is None
            assert view._post_call_hook is not None
        finally:
            del sys.modules["test_hooks_post_only"]

    async def test_tool_view_get_server_for_tool(self):
        """ToolView._get_server_for_tool() returns correct upstream server."""
        config = ToolViewConfig(
            tools={
                "server-a": {"tool_1": ToolConfig()},
                "server-b": {"tool_2": ToolConfig()},
            }
        )
        view = ToolView(name="test", config=config)

        # After initialization, should map tools to their servers
        assert view._get_server_for_tool("tool_1") == "server-a"
        assert view._get_server_for_tool("tool_2") == "server-b"

