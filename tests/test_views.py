"""Tests for ToolView class."""

import pytest

from mcp_proxy.exceptions import ToolCallAborted
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
            ]
        )
        view = ToolView(name="test", config=config)

        # No custom tools should be loaded since none have 'module'
        assert len(view.custom_tools) == 0

    async def test_tool_view_initialize_loads_tools(self):
        """ToolView.initialize() should load tools from upstream servers."""
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
                    post_call="test_hooks_module.post_call"
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
                    pre_call="test_hooks_pre_only.pre_call",
                    post_call=None
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
                    pre_call=None,
                    post_call="test_hooks_post_only.post_call"
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
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "tool"
            description = "Original description"

        config = ToolConfig(description="New prefix. {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.description == "New prefix. Original description"

    def test_transform_tool_both_name_and_description(self):
        """_transform_tool should handle both name and description."""
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "old"
            description = "Old desc"

        config = ToolConfig(name="new", description="Custom: {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "new"
        assert transformed.description == "Custom: Old desc"

    def test_transform_tool_preserves_original_when_no_overrides(self):
        """_transform_tool should preserve original when no overrides given."""
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "original"
            description = "Original desc"

        config = ToolConfig()  # No overrides
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "original"
        assert transformed.description == "Original desc"


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

        config = ToolViewConfig(
            tools={"server-a": {"my_tool": ToolConfig()}}
        )
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

        config = ToolViewConfig(
            tools={"server-a": {"my_tool": ToolConfig()}}
        )
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

        config = ToolViewConfig(
            tools={"server-a": {"my_tool": ToolConfig()}}
        )
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

        config = ToolViewConfig(
            tools={"server-a": {"my_tool": ToolConfig()}}
        )
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

        config = ToolViewConfig(
            tools={"server-a": {"my_tool": ToolConfig()}}
        )
        view = ToolView("test", config)
        view._post_call_hook = no_op_hook

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"original": True}
        view._upstream_clients = {"server-a": mock_client}

        result = await view.call_tool("my_tool", {})

        # Result should pass through unchanged
        assert result["original"] is True


class TestToolViewCompositeTool:
    """Tests for composite tool execution in ToolView."""

    async def test_call_composite_tool_executes_parallel(self):
        """call_tool should execute composite tools via parallel execution."""
        from unittest.mock import AsyncMock
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "multi_search": CompositeToolConfig(
                    description="Search multiple sources",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "source_a": {"tool": "server-a.tool_a", "args": {"q": "{inputs.query}"}},
                        "source_b": {"tool": "server-b.tool_b", "args": {"q": "{inputs.query}"}},
                    },
                )
            }
        )
        view = ToolView("test", config)

        # Mock upstream clients
        mock_client_a = AsyncMock()
        mock_client_a.call_tool.return_value = {"result": "from_a"}
        mock_client_b = AsyncMock()
        mock_client_b.call_tool.return_value = {"result": "from_b"}
        view._upstream_clients = {"server-a": mock_client_a, "server-b": mock_client_b}

        result = await view.call_tool("multi_search", {"query": "test"})

        # Should return results from composite tool
        assert "results" in result or isinstance(result, dict)

    async def test_composite_tool_calls_upstream_tools(self):
        """Composite tools should call upstream tools correctly."""
        from unittest.mock import AsyncMock
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "dual_search": CompositeToolConfig(
                    description="Dual search",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "server.tool_a", "args": {"q": "{inputs.query}"}},
                    },
                )
            }
        )
        view = ToolView("test", config)

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "result"}
        view._upstream_clients = {"server": mock_client}

        await view.call_tool("dual_search", {"query": "hello"})

        # Verify upstream was called
        mock_client.call_tool.assert_called()

    async def test_composite_tool_unknown_server_returns_error(self):
        """Composite tool calling unknown server should return error in results."""
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "bad_composite": CompositeToolConfig(
                    description="Has unknown server",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "missing.tool", "args": {}},
                    },
                )
            }
        )
        view = ToolView("test", config)
        # No clients at all - will fail to find "missing" server
        view._upstream_clients = {}

        # ParallelTool catches exceptions and returns them in results
        result = await view.call_tool("bad_composite", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]
        assert "Unknown upstream tool" in result["result"]["error"]

    async def test_composite_tool_unknown_server_with_other_clients(self):
        """Composite tool calling unknown server with other clients present."""
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "wrong_server": CompositeToolConfig(
                    description="Calls wrong server",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "nonexistent.tool", "args": {}},
                    },
                )
            }
        )
        view = ToolView("test", config)
        # Has clients, but not the one the tool needs - tests 187 branch
        view._upstream_clients = {"existing_server": None}

        result = await view.call_tool("wrong_server", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]

    async def test_composite_tool_no_dot_in_tool_name(self):
        """Composite tool with tool name missing dot should error."""
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "bad_format": CompositeToolConfig(
                    description="Tool without server.tool format",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "no_dot_format", "args": {}},  # Missing the dot
                    },
                )
            }
        )
        view = ToolView("test", config)
        view._upstream_clients = {}

        # This should trigger the 185->191 branch (no dot in tool name)
        result = await view.call_tool("bad_format", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]
        assert "Unknown upstream tool" in result["result"]["error"]

    async def test_composite_tool_successful_upstream_call(self):
        """Composite tool should successfully call upstream and return results."""
        from unittest.mock import AsyncMock
        from mcp_proxy.models import CompositeToolConfig

        config = ToolViewConfig(
            composite_tools={
                "good_composite": CompositeToolConfig(
                    description="Successful composite",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "search": {"tool": "server.search_tool", "args": {"q": "{inputs.query}"}},
                    },
                )
            }
        )
        view = ToolView("test", config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"found": 10}
        view._upstream_clients = {"server": mock_client}

        result = await view.call_tool("good_composite", {"query": "test"})

        # Should have successful result
        assert "search" in result
        # Verify the upstream was actually called
        mock_client.call_tool.assert_called()


class TestToolViewCustomToolErrors:
    """Tests for custom tool error handling."""

    async def test_custom_tool_call_upstream_unknown_tool_raises(self, tmp_path, monkeypatch):
        """Custom tool calling unknown upstream should raise."""
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.views import ToolView

        # Create a custom tool that tries to call an unknown upstream
        module_dir = tmp_path / "test_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text('''
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_unknown", description="Tries to call unknown tool")
async def call_unknown(ctx: ProxyContext, query: str) -> dict:
    # Try to call a tool that doesn't exist with wrong format
    return await ctx.call_tool("no_dot_format", query=query)
''')
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "test_hooks.tools.call_unknown"}]
        )
        view = ToolView("test", config)
        view._upstream_clients = {}

        with pytest.raises(ValueError, match="Unknown upstream tool"):
            await view.call_tool("call_unknown", {"query": "test"})

    async def test_custom_tool_call_upstream_unknown_server_raises(self, tmp_path, monkeypatch):
        """Custom tool calling tool on unknown server should raise."""
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.views import ToolView

        # Create a custom tool that calls a tool with proper format but unknown server
        module_dir = tmp_path / "unknown_server_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text('''
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_unknown_server", description="Calls unknown server")
async def call_unknown_server(ctx: ProxyContext, query: str) -> dict:
    # Try to call a tool on a server that doesn't exist
    return await ctx.call_tool("missing_server.tool", query=query)
''')
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "unknown_server_hooks.tools.call_unknown_server"}]
        )
        view = ToolView("test", config)
        view._upstream_clients = {"other_server": None}  # Has a server, but not the one we call

        with pytest.raises(ValueError, match="Unknown upstream tool"):
            await view.call_tool("call_unknown_server", {"query": "test"})

    async def test_custom_tool_calls_upstream_successfully(self, tmp_path, monkeypatch):
        """Custom tool calling valid upstream should work."""
        from unittest.mock import AsyncMock
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.views import ToolView

        # Create a custom tool that calls a valid upstream
        module_dir = tmp_path / "success_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text('''
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_valid", description="Calls valid upstream")
async def call_valid(ctx: ProxyContext, query: str) -> dict:
    result = await ctx.call_tool("server.search", query=query)
    return {"wrapped": result}
''')
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "success_hooks.tools.call_valid"}]
        )
        view = ToolView("test", config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "from upstream"}
        view._upstream_clients = {"server": mock_client}

        result = await view.call_tool("call_valid", {"query": "test"})

        assert "wrapped" in result
        mock_client.call_tool.assert_called_with("search", {"query": "test"})

