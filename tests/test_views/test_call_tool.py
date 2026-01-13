"""Tests for calling tools through a view."""

import pytest

from mcp_proxy.exceptions import ToolCallAborted
from mcp_proxy.hooks import HookResult
from mcp_proxy.models import ToolConfig, ToolViewConfig
from mcp_proxy.proxy.tool_info import ToolInfo
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


class TestToolViewUpdateToolMapping:
    """Tests for update_tool_mapping method."""

    async def test_update_tool_mapping_adds_discovered_tools(self):
        """update_tool_mapping should add dynamically discovered tools to mapping."""
        from unittest.mock import AsyncMock

        # Empty config - no tools explicitly configured
        config = ToolViewConfig()
        view = ToolView("test", config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "success"}
        view._upstream_clients = {"ynab-server": mock_client}

        # Simulate discovered tools from upstream (like YNAB tools)
        discovered_tools = [
            ToolInfo(name="list-categories", server="ynab-server"),
            ToolInfo(name="list-budgets", server="ynab-server"),
            ToolInfo(name="bulk-manage-transactions", server="ynab-server"),
        ]

        # Before update, tool should not be found
        assert view._get_server_for_tool("list-categories") == ""

        # Update mapping
        view.update_tool_mapping(discovered_tools)

        # Now tools should be mapped
        assert view._get_server_for_tool("list-categories") == "ynab-server"
        assert view._get_server_for_tool("list-budgets") == "ynab-server"
        assert view._get_server_for_tool("bulk-manage-transactions") == "ynab-server"

        # Call should work now
        result = await view.call_tool("list-categories", {"budget_id": "123"})
        mock_client.call_tool.assert_called_with(
            "list-categories", {"budget_id": "123"}
        )
        assert result == {"result": "success"}

    async def test_update_tool_mapping_preserves_explicit_config(self):
        """update_tool_mapping should not overwrite explicitly configured tools."""
        # Explicitly configure a tool with rename
        config = ToolViewConfig(
            tools={"server-a": {"original_name": ToolConfig(name="renamed_tool")}}
        )
        view = ToolView("test", config)

        # Try to update with same tool (different server)
        discovered_tools = [
            ToolInfo(name="renamed_tool", server="different-server"),
        ]

        view.update_tool_mapping(discovered_tools)

        # Should still point to original server, not overwritten
        assert view._get_server_for_tool("renamed_tool") == "server-a"

    async def test_update_tool_mapping_handles_renamed_tools(self):
        """update_tool_mapping should track original names for renamed tools."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig()
        view = ToolView("test", config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "ok"}
        view._upstream_clients = {"server-a": mock_client}

        # Tool that was renamed upstream
        discovered_tools = [
            ToolInfo(
                name="friendly_name",
                server="server-a",
                original_name="ugly_internal_name",
            ),
        ]

        view.update_tool_mapping(discovered_tools)

        # Should map friendly name to server
        assert view._get_server_for_tool("friendly_name") == "server-a"
        # Should track original name
        assert view._get_original_tool_name("friendly_name") == "ugly_internal_name"

        # When called, should use original name
        await view.call_tool("friendly_name", {})
        mock_client.call_tool.assert_called_with("ugly_internal_name", {})


class TestToolViewCaching:
    """Tests for output caching in ToolView."""

    async def test_call_tool_applies_caching(self, tmp_path):
        """ToolView.call_tool() should apply caching when configured."""
        from unittest.mock import AsyncMock, patch

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.views import CacheContext

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "x" * 1000}
        view._upstream_clients = {"server-a": mock_client}

        # Set up cache context
        def get_cache_config(tool_name, server_name):
            return OutputCacheConfig(enabled=True, ttl_seconds=3600, preview_chars=100)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            result = await view.call_tool("my_tool", {"arg": "value"})

        # Result should be cached response
        assert result["cached"] is True
        assert "token" in result
        assert "retrieve_url" in result
        assert "preview" in result

    async def test_call_tool_skips_caching_below_min_size(self, tmp_path):
        """ToolView.call_tool() should skip caching for small outputs."""
        from unittest.mock import AsyncMock, patch

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.views import CacheContext

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)

        # Mock upstream client with small result
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "small"}
        view._upstream_clients = {"server-a": mock_client}

        # Set up cache context with min_size
        def get_cache_config(tool_name, server_name):
            return OutputCacheConfig(
                enabled=True, ttl_seconds=3600, preview_chars=100, min_size=10000
            )

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            result = await view.call_tool("my_tool", {"arg": "value"})

        # Result should NOT be cached (too small)
        assert result == {"result": "small"}

    async def test_call_tool_no_caching_when_config_returns_none(self, tmp_path):
        """ToolView.call_tool() should not cache when config returns None."""
        from unittest.mock import AsyncMock, patch

        from mcp_proxy.views import CacheContext

        config = ToolViewConfig(tools={"server-a": {"my_tool": ToolConfig()}})
        view = ToolView("test", config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "data"}
        view._upstream_clients = {"server-a": mock_client}

        # Set up cache context that returns None
        def get_cache_config(tool_name, server_name):
            return None

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            result = await view.call_tool("my_tool", {"arg": "value"})

        # Result should NOT be cached
        assert result == {"result": "data"}

    async def test_apply_caching_with_string_result(self, tmp_path):
        """_apply_caching should handle string results."""
        from unittest.mock import patch

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.views import CacheContext

        config = ToolViewConfig()
        view = ToolView("test", config)

        def get_cache_config(tool_name, server_name):
            return OutputCacheConfig(enabled=True)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            cache_config = OutputCacheConfig(enabled=True, preview_chars=10)
            result = view._apply_caching("hello world", cache_config)

        assert result["cached"] is True
        assert result["preview"] == "hello worl..."

    async def test_apply_caching_with_dict_result(self, tmp_path):
        """_apply_caching should handle dict results by JSON serializing them."""
        from unittest.mock import patch

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.views import CacheContext

        config = ToolViewConfig()
        view = ToolView("test", config)

        def get_cache_config(tool_name, server_name):
            return OutputCacheConfig(enabled=True)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            cache_config = OutputCacheConfig(enabled=True, preview_chars=100)
            result = view._apply_caching({"key": "value"}, cache_config)

        assert result["cached"] is True
        # The preview should contain the JSON representation
        assert "key" in result["preview"]

    async def test_apply_caching_json_dumps_fallback(self, tmp_path):
        """_apply_caching should fall back to str() when json.dumps fails."""
        import json
        from unittest.mock import patch

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.views import CacheContext

        config = ToolViewConfig()
        view = ToolView("test", config)

        def get_cache_config(tool_name, server_name):
            return OutputCacheConfig(enabled=True)

        # Create a mock that raises on first call (in _apply_caching)
        # but works on subsequent calls (in cache module)
        call_count = [0]
        original_dumps = json.dumps

        def mock_dumps(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TypeError("Simulated failure")
            return original_dumps(*args, **kwargs)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            view._cache_context = CacheContext(
                get_cache_config=get_cache_config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

            cache_config = OutputCacheConfig(enabled=True, preview_chars=100)

            # Patch json.dumps globally (it's imported inside the function)
            with patch("json.dumps", mock_dumps):
                result = view._apply_caching({"key": "value"}, cache_config)

        assert result["cached"] is True
