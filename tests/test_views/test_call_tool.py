"""Tests for calling tools through a view."""

import pytest

from mcp_proxy.exceptions import ToolCallAborted
from mcp_proxy.hooks import HookResult
from mcp_proxy.models import ToolConfig, ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolViewCallTool:
    """Tests for calling tools through a view."""

    async def test_call_tool_executes_upstream(self):
        """ToolView.call_tool() should execute the upstream tool."""
        view = ToolView("test", ToolViewConfig())

        # Without actual upstream, this should fail
        with pytest.raises(ValueError, match="Unknown tool"):
            await view.call_tool("nonexistent_tool", {"arg": "value"})

    async def test_call_tool_with_mock_upstream(self):
        """ToolView.call_tool() should call upstream and return result."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "success"}
        view._upstream_clients = {"server-a": mock_client}

        result = await view.call_tool("my_tool", {"arg": "value"})

        mock_client.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
        assert result == {"result": "success"}

    async def test_call_tool_applies_pre_hook(self):
        """ToolView.call_tool() should apply pre-call hooks."""
        from unittest.mock import AsyncMock

        async def modify_args(args, context):
            args["modified"] = True
            return HookResult(args=args)

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)
        view._pre_call_hook = modify_args

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "ok"}
        view._upstream_clients = {"server-a": mock_client}

        await view.call_tool("my_tool", {"arg": "value"})

        # Should have modified args
        call_args = mock_client.call_tool.call_args
        assert call_args[0][1]["modified"] is True

    async def test_call_tool_applies_post_hook(self):
        """ToolView.call_tool() should apply post-call hooks."""
        from unittest.mock import AsyncMock

        async def transform_result(result, args, context):
            return HookResult(result={"transformed": True, **result})

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)
        view._post_call_hook = transform_result

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"original": "data"}
        view._upstream_clients = {"server-a": mock_client}

        result = await view.call_tool("my_tool", {})

        assert result["transformed"] is True
        assert result["original"] == "data"

    async def test_call_tool_aborts_on_pre_hook_abort(self):
        """ToolView.call_tool() should not execute if pre-hook aborts."""

        async def abort_hook(args, context):
            return HookResult(abort=True, abort_reason="Blocked")

        view = ToolView("test", ToolViewConfig())
        view._pre_call_hook = abort_hook

        # Should raise ToolCallAborted without calling upstream
        with pytest.raises(ToolCallAborted):
            await view.call_tool("any_tool", {})

    async def test_call_tool_raises_tool_call_aborted(self):
        """ToolView.call_tool() should raise ToolCallAborted on abort."""

        async def abort_hook(args, context):
            return HookResult(abort=True, abort_reason="Unauthorized")

        view = ToolView("test", ToolViewConfig())
        view._pre_call_hook = abort_hook

        with pytest.raises(ToolCallAborted) as exc_info:
            await view.call_tool("any_tool", {})

        assert "Unauthorized" in str(exc_info.value)

    async def test_call_tool_pre_hook_no_args_modification(self):
        """ToolView.call_tool() handles pre-hook that doesn't modify args."""
        from unittest.mock import AsyncMock

        async def no_op_hook(args, context):
            return HookResult()  # No args modification

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)
        view._pre_call_hook = no_op_hook

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "ok"}
        view._upstream_clients = {"server-a": mock_client}

        await view.call_tool("my_tool", {"original": "value"})

        # Args should pass through unchanged
        call_args = mock_client.call_tool.call_args
        assert call_args[0][1]["original"] == "value"

    async def test_call_tool_post_hook_no_result_modification(self):
        """ToolView.call_tool() handles post-hook that doesn't modify result."""
        from unittest.mock import AsyncMock

        async def no_op_hook(result, args, context):
            return HookResult()  # No result modification (result=None)

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)
        view._post_call_hook = no_op_hook

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"original": True}
        view._upstream_clients = {"server-a": mock_client}

        result = await view.call_tool("my_tool", {})

        # Result should pass through unchanged
        assert result["original"] is True
