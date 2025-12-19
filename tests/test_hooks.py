"""Tests for the hook system."""

import pytest


class TestToolCallContext:
    """Tests for ToolCallContext dataclass."""

    def test_context_creation(self):
        """ToolCallContext should hold call metadata."""
        from mcp_proxy.hooks import ToolCallContext

        ctx = ToolCallContext(
            view_name="redis-expert",
            tool_name="search_knowledge",
            upstream_server="redis-memory-server"
        )
        assert ctx.view_name == "redis-expert"
        assert ctx.tool_name == "search_knowledge"
        assert ctx.upstream_server == "redis-memory-server"


class TestHookResult:
    """Tests for HookResult class."""

    def test_hook_result_passthrough(self):
        """HookResult with no modifications passes through."""
        from mcp_proxy.hooks import HookResult

        result = HookResult()
        assert result.args is None
        assert result.result is None
        assert result.abort is False
        assert result.abort_reason is None

    def test_hook_result_modify_args(self):
        """HookResult can modify arguments."""
        from mcp_proxy.hooks import HookResult

        result = HookResult(args={"query": "modified"})
        assert result.args == {"query": "modified"}

    def test_hook_result_modify_result(self):
        """HookResult can modify the result (post-call)."""
        from mcp_proxy.hooks import HookResult

        result = HookResult(result={"data": "transformed"})
        assert result.result == {"data": "transformed"}

    def test_hook_result_abort(self):
        """HookResult can abort a call."""
        from mcp_proxy.hooks import HookResult

        result = HookResult(abort=True, abort_reason="Unauthorized")
        assert result.abort is True
        assert result.abort_reason == "Unauthorized"


class TestLoadHook:
    """Tests for dynamic hook loading."""

    def test_load_hook_from_dotted_path(self, tmp_path):
        """load_hook should import a function from a dotted path."""
        from mcp_proxy.hooks import load_hook

        # Create a temporary hook module
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "__init__.py").write_text("")
        (hooks_dir / "test_hooks.py").write_text(
            "async def my_pre_call(args, context): return args"
        )

        import sys
        sys.path.insert(0, str(tmp_path))
        try:
            hook = load_hook("hooks.test_hooks.my_pre_call")
            assert callable(hook)
        finally:
            sys.path.remove(str(tmp_path))

    def test_load_hook_invalid_path(self):
        """load_hook should raise on invalid path."""
        from mcp_proxy.hooks import load_hook

        with pytest.raises(ImportError):
            load_hook("nonexistent.module.function")


class TestPreCallHook:
    """Tests for pre-call hook execution."""

    async def test_pre_call_hook_modifies_args(self):
        """Pre-call hook can modify arguments before tool execution."""
        from mcp_proxy.hooks import ToolCallContext, HookResult, execute_pre_call

        async def add_prefix(args: dict, context: ToolCallContext) -> HookResult:
            args["query"] = "prefix: " + args.get("query", "")
            return HookResult(args=args)

        context = ToolCallContext("view", "tool", "server")
        original_args = {"query": "test"}
        result = await execute_pre_call(add_prefix, original_args, context)

        assert result.args["query"] == "prefix: test"

    async def test_pre_call_hook_aborts(self):
        """Pre-call hook can abort a call."""
        from mcp_proxy.hooks import ToolCallContext, HookResult, execute_pre_call

        async def deny_all(args: dict, context: ToolCallContext) -> HookResult:
            return HookResult(abort=True, abort_reason="Denied")

        context = ToolCallContext("view", "tool", "server")
        result = await execute_pre_call(deny_all, {"query": "test"}, context)

        assert result.abort is True
        assert result.abort_reason == "Denied"


class TestPostCallHook:
    """Tests for post-call hook execution."""

    async def test_post_call_hook_transforms_result(self):
        """Post-call hook can transform the result."""
        from mcp_proxy.hooks import ToolCallContext, HookResult, execute_post_call

        async def add_metadata(
            result: dict, args: dict, context: ToolCallContext
        ) -> HookResult:
            result["_view"] = context.view_name
            return HookResult(result=result)

        context = ToolCallContext("redis-expert", "tool", "server")
        original_result = {"data": "value"}
        hook_result = await execute_post_call(
            add_metadata, original_result, {}, context
        )

        assert hook_result.result["_view"] == "redis-expert"

