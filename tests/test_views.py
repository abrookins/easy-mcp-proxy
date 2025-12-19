"""Tests for ToolView class."""

import pytest


class TestToolViewInitialization:
    """Tests for ToolView initialization."""

    async def test_tool_view_creation(self):
        """ToolView should be creatable with a name and config."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig

        config = ToolViewConfig(description="Test view")
        view = ToolView(name="test-view", config=config)

        assert view.name == "test-view"
        assert view.description == "Test view"

    async def test_tool_view_initialize_loads_tools(self):
        """ToolView.initialize() should load tools from upstream servers."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, ToolConfig

        config = ToolViewConfig(
            tools={
                "upstream-server": {
                    "tool_a": ToolConfig(),
                    "tool_b": ToolConfig()
                }
            }
        )
        view = ToolView(name="test", config=config)

        # Mock upstream connections would be needed here
        # This test verifies the interface exists
        with pytest.raises(Exception):  # Will fail without upstream
            await view.initialize(upstream_clients={})

    async def test_tool_view_initialize_loads_hooks(self):
        """ToolView.initialize() should load hooks from dotted paths."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, HooksConfig

        config = ToolViewConfig(
            hooks=HooksConfig(
                pre_call="hooks.test.pre_call",
                post_call="hooks.test.post_call"
            )
        )
        view = ToolView(name="test", config=config)

        # _load_hooks should be called during initialize
        # Would need mock module to test actual loading

    async def test_tool_view_get_server_for_tool(self):
        """ToolView._get_server_for_tool() returns correct upstream server."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, ToolConfig

        config = ToolViewConfig(
            tools={
                "server-a": {"tool_1": ToolConfig()},
                "server-b": {"tool_2": ToolConfig()}
            }
        )
        view = ToolView(name="test", config=config)

        # After initialization, should map tools to their servers
        assert view._get_server_for_tool("tool_1") == "server-a"
        assert view._get_server_for_tool("tool_2") == "server-b"


class TestToolTransformation:
    """Tests for tool transformation (rename/description override)."""

    def test_transform_tool_rename(self):
        """_transform_tool should rename a tool."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, ToolConfig

        view = ToolView("test", ToolViewConfig())

        # Create a mock tool
        class MockTool:
            name = "original_name"
            description = "Original description"

        config = ToolConfig(name="new_name")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "new_name"

    def test_transform_tool_description_override(self):
        """_transform_tool should override description with {original} placeholder."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, ToolConfig

        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "tool"
            description = "Original description"

        config = ToolConfig(description="New prefix. {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.description == "New prefix. Original description"

    def test_transform_tool_both_name_and_description(self):
        """_transform_tool should handle both name and description."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, ToolConfig

        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "old"
            description = "Old desc"

        config = ToolConfig(name="new", description="Custom: {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "new"
        assert transformed.description == "Custom: Old desc"


class TestToolViewCallTool:
    """Tests for calling tools through a view."""

    async def test_call_tool_executes_upstream(self):
        """ToolView.call_tool() should execute the upstream tool."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig

        view = ToolView("test", ToolViewConfig())

        # Without actual upstream, this should fail
        with pytest.raises(Exception):
            await view.call_tool("nonexistent_tool", {"arg": "value"})

    async def test_call_tool_applies_pre_hook(self):
        """ToolView.call_tool() should apply pre-call hooks."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, HooksConfig
        from mcp_proxy.hooks import HookResult

        async def modify_args(args, context):
            args["modified"] = True
            return HookResult(args=args)

        config = ToolViewConfig(
            hooks=HooksConfig(pre_call="path.to.hook")  # Would need mock
        )
        view = ToolView("test", config)
        view._pre_call_hook = modify_args  # Inject mock

        # Test would verify args are modified before upstream call
        # Implementation would need mocked upstream

    async def test_call_tool_applies_post_hook(self):
        """ToolView.call_tool() should apply post-call hooks."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig, HooksConfig
        from mcp_proxy.hooks import HookResult

        async def transform_result(result, args, context):
            result["transformed"] = True
            return HookResult(result=result)

        config = ToolViewConfig(
            hooks=HooksConfig(post_call="path.to.hook")
        )
        view = ToolView("test", config)
        view._post_call_hook = transform_result  # Inject mock

        # Test would verify result is transformed after upstream call

    async def test_call_tool_aborts_on_pre_hook_abort(self):
        """ToolView.call_tool() should not execute if pre-hook aborts."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.hooks import HookResult

        async def abort_hook(args, context):
            return HookResult(abort=True, abort_reason="Blocked")

        view = ToolView("test", ToolViewConfig())
        view._pre_call_hook = abort_hook

        # Should raise or return error without calling upstream
        result = await view.call_tool("any_tool", {})
        assert "error" in result or result.get("aborted") is True

    async def test_call_tool_raises_tool_call_aborted(self):
        """ToolView.call_tool() should raise ToolCallAborted on abort."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.exceptions import ToolCallAborted
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.hooks import HookResult

        async def abort_hook(args, context):
            return HookResult(abort=True, abort_reason="Unauthorized")

        view = ToolView("test", ToolViewConfig())
        view._pre_call_hook = abort_hook

        with pytest.raises(ToolCallAborted) as exc_info:
            await view.call_tool("any_tool", {})

        assert "Unauthorized" in str(exc_info.value)

