"""Tests for hook wrapping of tools."""

from mcp_proxy.hooks import HookResult
from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy


class TestMCPProxyHookWrapping:
    """Tests for hook wrapping of tools."""

    async def test_wrap_tool_with_hooks(self):
        """_wrap_tool_with_hooks adds pre/post hook execution."""
        call_log = []

        async def pre_hook(args, ctx):
            call_log.append("pre")
            return HookResult(args=args)

        async def post_hook(result, args, ctx):
            call_log.append("post")
            return HookResult(result=result)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        await wrapped(query="test")

        assert call_log == ["pre", "tool", "post"]

    async def test_wrap_tool_without_hooks(self):
        """_wrap_tool_with_hooks works without any hooks."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            return {"result": "ok", "args": kwargs}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        result = await wrapped(query="test")

        assert result == {"result": "ok", "args": {"query": "test"}}

    async def test_wrap_tool_with_pre_hook_only(self):
        """_wrap_tool_with_hooks works with only pre_hook."""
        call_log = []

        async def pre_hook(args, ctx):
            call_log.append("pre")
            return HookResult(args=args)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        await wrapped()

        assert call_log == ["pre", "tool"]

    async def test_wrap_tool_with_post_hook_only(self):
        """_wrap_tool_with_hooks works with only post_hook."""
        call_log = []

        async def post_hook(result, args, ctx):
            call_log.append("post")
            return HookResult(result=result)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        await wrapped()

        assert call_log == ["tool", "post"]

    async def test_wrap_tool_pre_hook_no_args_modification(self):
        """_wrap_tool_with_hooks handles pre_hook that doesn't modify args."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def pre_hook(args, ctx):
            return HookResult()  # No args modification

        async def original_tool(**kwargs):
            return {"args": kwargs}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        result = await wrapped(query="test")

        # Args should pass through unchanged
        assert result["args"]["query"] == "test"

    async def test_wrap_tool_post_hook_no_result_modification(self):
        """_wrap_tool_with_hooks handles post_hook that doesn't modify result."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def post_hook(result, args, ctx):
            return HookResult()  # No result modification (result=None)

        async def original_tool(**kwargs):
            return {"original": True}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server",
        )

        result = await wrapped()

        # Result should pass through unchanged
        assert result["original"] is True
