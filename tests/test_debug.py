"""Tests for the debug instrumentation module."""

import logging

import pytest

from mcp_proxy.debug import (
    CallMetrics,
    DebugContext,
    _format_args,
    _format_value,
    _summarize_result,
    _truncate,
    clear_request_id,
    configure_debug_logging,
    disable_debug,
    enable_debug,
    get_request_id,
    instrument_client_manager,
    instrument_proxy,
    instrument_view,
    is_debug_enabled,
    set_request_id,
    timed_tool,
    timed_upstream_call,
)


class TestDebugState:
    """Tests for debug enable/disable state."""

    def test_is_debug_enabled_default_false(self, monkeypatch):
        """Debug should be disabled by default."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()
        assert is_debug_enabled() is False

    def test_enable_debug_programmatically(self, monkeypatch):
        """enable_debug() should enable debug mode."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()
        enable_debug()
        assert is_debug_enabled() is True
        disable_debug()

    def test_disable_debug(self, monkeypatch):
        """disable_debug() should disable debug mode."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        disable_debug()
        assert is_debug_enabled() is False

    @pytest.mark.parametrize("env_value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_debug_enabled_via_env_var(self, monkeypatch, env_value):
        """MCP_PROXY_DEBUG env var should enable debug mode."""
        disable_debug()
        monkeypatch.setenv("MCP_PROXY_DEBUG", env_value)
        assert is_debug_enabled() is True

    @pytest.mark.parametrize("env_value", ["0", "false", "no", ""])
    def test_debug_disabled_via_env_var(self, monkeypatch, env_value):
        """Other env var values should not enable debug mode."""
        disable_debug()
        monkeypatch.setenv("MCP_PROXY_DEBUG", env_value)
        assert is_debug_enabled() is False


class TestRequestId:
    """Tests for request ID management."""

    def test_get_request_id_creates_new(self):
        """get_request_id() should create a new ID if none exists."""
        clear_request_id()
        req_id = get_request_id()
        assert req_id is not None
        assert len(req_id) == 8

    def test_get_request_id_returns_same(self):
        """get_request_id() should return the same ID within context."""
        clear_request_id()
        id1 = get_request_id()
        id2 = get_request_id()
        assert id1 == id2

    def test_set_request_id(self):
        """set_request_id() should set a specific ID."""
        set_request_id("test1234")
        assert get_request_id() == "test1234"

    def test_set_request_id_generates(self):
        """set_request_id() with no arg should generate new ID."""
        clear_request_id()
        new_id = set_request_id()
        assert new_id is not None
        assert len(new_id) == 8
        assert get_request_id() == new_id

    def test_clear_request_id(self):
        """clear_request_id() should clear the current ID."""
        set_request_id("test1234")
        clear_request_id()
        # After clear, get_request_id creates a new one
        new_id = get_request_id()
        assert new_id != "test1234"


class TestCallMetrics:
    """Tests for CallMetrics dataclass."""

    def test_metrics_creation(self):
        """CallMetrics should track tool call data."""
        metrics = CallMetrics(
            tool_name="test_tool",
            view_name="test_view",
            server_name="test_server",
            request_id="abc12345",
        )
        assert metrics.tool_name == "test_tool"
        assert metrics.view_name == "test_view"
        assert metrics.server_name == "test_server"
        assert metrics.request_id == "abc12345"
        assert metrics.success is True
        assert metrics.error is None

    def test_metrics_elapsed_time(self):
        """CallMetrics should calculate elapsed time."""
        metrics = CallMetrics(tool_name="test")
        # Before complete, elapsed should be positive
        assert metrics.elapsed_ms > 0
        metrics.complete()
        # After complete, elapsed should be fixed
        elapsed = metrics.elapsed_ms
        assert elapsed >= 0

    def test_metrics_complete_with_error(self):
        """complete() should record errors."""
        metrics = CallMetrics(tool_name="test")
        metrics.complete(success=False, error="Something went wrong")
        assert metrics.success is False
        assert metrics.error == "Something went wrong"


class TestFormatting:
    """Tests for formatting helper functions."""

    def test_truncate_short_string(self):
        """_truncate() should not modify short strings."""
        assert _truncate("short", 100) == "short"

    def test_truncate_long_string(self):
        """_truncate() should truncate long strings with ellipsis."""
        result = _truncate("a" * 150, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_format_value_none(self):
        """_format_value() should handle None."""
        assert _format_value(None) == "None"

    def test_format_value_string(self):
        """_format_value() should format strings with repr."""
        assert _format_value("hello") == "'hello'"

    def test_format_value_dict(self):
        """_format_value() should format dicts as JSON."""
        result = _format_value({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_format_value_list(self):
        """_format_value() should format lists as JSON."""
        result = _format_value([1, 2, 3])
        assert "[1, 2, 3]" in result

    def test_format_value_non_serializable(self):
        """_format_value() should handle non-JSON-serializable objects."""

        class NonSerializable:
            def __str__(self):
                return "non-serializable-object"

        result = _format_value(NonSerializable())
        assert "non-serializable-object" in result

    def test_format_value_other_type(self):
        """_format_value() should handle other types with str()."""
        result = _format_value(12345)
        assert "12345" in result

    def test_format_value_dict_json_error(self, monkeypatch):
        """_format_value() should handle dicts that cause json.dumps to fail."""

        def failing_dumps(*args, **kwargs):
            raise TypeError("Cannot serialize")

        # Need to patch the json module in the debug module's namespace
        import mcp_proxy.debug as debug_module

        monkeypatch.setattr(
            debug_module, "json", type("json", (), {"dumps": failing_dumps})()
        )

        # Create a dict and call _format_value
        result = debug_module._format_value({"key": "value"})
        # It should fall back to str() representation
        assert "key" in result or "{" in result

    def test_format_args_empty(self):
        """_format_args() should handle empty args."""
        assert _format_args({}) == "{}"

    def test_format_args_simple(self):
        """_format_args() should format simple args."""
        result = _format_args({"query": "test"})
        assert "query=" in result
        assert "test" in result

    def test_summarize_result_none(self):
        """_summarize_result() should handle None."""
        assert _summarize_result(None) == "None"

    def test_summarize_result_dict(self):
        """_summarize_result() should summarize dicts."""
        result = _summarize_result({"a": 1, "b": 2})
        assert "dict" in result
        assert "'a'" in result or "a" in result

    def test_summarize_result_list(self):
        """_summarize_result() should summarize lists."""
        result = _summarize_result([1, 2, 3])
        assert "list(3 items)" == result

    def test_summarize_result_string(self):
        """_summarize_result() should summarize strings."""
        result = _summarize_result("hello world")
        assert "str(11 chars)" == result

    def test_summarize_result_calltoolresult(self):
        """_summarize_result() should handle CallToolResult-like objects."""

        class MockResult:
            content = [{"text": "item1"}, {"text": "item2"}]

        result = _summarize_result(MockResult())
        assert "CallToolResult(2 items)" == result

    def test_summarize_result_unknown_type(self):
        """_summarize_result() should return type name for unknown types."""

        class CustomType:
            pass

        result = _summarize_result(CustomType())
        assert result == "CustomType"


class TestTimedTool:
    """Tests for the timed_tool decorator."""

    async def test_timed_tool_disabled_no_overhead(self, monkeypatch):
        """timed_tool should have no overhead when debug disabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()

        call_count = 0

        async def my_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            return {"result": "ok"}

        wrapped = timed_tool(my_tool, tool_name="my_tool")
        result = await wrapped(query="test")

        assert call_count == 1
        assert result == {"result": "ok"}

    async def test_timed_tool_enabled_logs(self, monkeypatch, caplog):
        """timed_tool should log when debug enabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def my_tool(**kwargs):
            return {"result": "ok"}

        wrapped = timed_tool(my_tool, tool_name="test_tool", view_name="test_view")

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await wrapped(query="test")

        assert result == {"result": "ok"}
        # Check that logging happened
        log_text = caplog.text
        assert "CALL" in log_text or "DONE" in log_text
        disable_debug()

    async def test_timed_tool_logs_exception(self, monkeypatch, caplog):
        """timed_tool should log errors."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def failing_tool(**kwargs):
            raise ValueError("test error")

        wrapped = timed_tool(failing_tool, tool_name="fail_tool")

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            with pytest.raises(ValueError, match="test error"):
                await wrapped()

        log_text = caplog.text
        assert "FAIL" in log_text
        disable_debug()

    async def test_timed_tool_with_server_name(self, monkeypatch, caplog):
        """timed_tool should include server_name in context when provided."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def my_tool(**kwargs):
            return {"result": "ok"}

        wrapped = timed_tool(
            my_tool, tool_name="test_tool", view_name="test_view", server_name="my_srv"
        )

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await wrapped(query="test")

        assert result == {"result": "ok"}
        log_text = caplog.text
        assert "server=my_srv" in log_text
        disable_debug()

    async def test_timed_tool_logs_slow_call(self, monkeypatch, caplog):
        """timed_tool should log warning for slow calls."""
        import asyncio

        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def slow_tool(**kwargs):
            await asyncio.sleep(0.15)  # 150ms > 100ms threshold
            return {"result": "slow"}

        wrapped = timed_tool(slow_tool, tool_name="slow_tool")

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await wrapped()

        assert result == {"result": "slow"}
        log_text = caplog.text
        assert "SLOW" in log_text
        disable_debug()


class TestTimedUpstreamCall:
    """Tests for the timed_upstream_call decorator."""

    async def test_upstream_call_disabled(self, monkeypatch):
        """timed_upstream_call should pass through when disabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()

        async def call_tool(server_name, tool_name, args):
            return {"result": "ok"}

        wrapped = timed_upstream_call(call_tool)
        result = await wrapped("server", "tool", {"arg": "value"})

        assert result == {"result": "ok"}

    async def test_upstream_call_enabled(self, monkeypatch, caplog):
        """timed_upstream_call should log when enabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def call_tool(server_name, tool_name, args):
            return {"result": "ok"}

        wrapped = timed_upstream_call(call_tool)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await wrapped("my_server", "my_tool", {"arg": "value"})

        assert result == {"result": "ok"}
        log_text = caplog.text
        assert "UPSTREAM" in log_text
        disable_debug()

    async def test_upstream_call_logs_slow(self, monkeypatch, caplog):
        """timed_upstream_call should log warning for slow calls."""
        import asyncio

        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def slow_call(server_name, tool_name, args):
            await asyncio.sleep(0.06)  # 60ms > 50ms threshold
            return {"result": "slow"}

        wrapped = timed_upstream_call(slow_call)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await wrapped("srv", "tool", {})

        assert result == {"result": "slow"}
        log_text = caplog.text
        assert "UPSTREAM_SLOW" in log_text
        disable_debug()

    async def test_upstream_call_logs_exception(self, monkeypatch, caplog):
        """timed_upstream_call should log errors and re-raise."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def failing_call(server_name, tool_name, args):
            raise ConnectionError("Connection failed")

        wrapped = timed_upstream_call(failing_call)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            with pytest.raises(ConnectionError, match="Connection failed"):
                await wrapped("srv", "tool", {})

        log_text = caplog.text
        assert "UPSTREAM_FAIL" in log_text
        disable_debug()


class TestDebugContext:
    """Tests for the DebugContext context manager."""

    def test_debug_context_sets_request_id(self):
        """DebugContext should set request ID."""
        clear_request_id()
        with DebugContext("req12345") as ctx:
            assert ctx.request_id == "req12345"
            assert get_request_id() == "req12345"

    def test_debug_context_generates_request_id(self):
        """DebugContext should generate ID if none provided."""
        clear_request_id()
        with DebugContext() as ctx:
            assert ctx.request_id is not None
            assert len(ctx.request_id) == 8

    async def test_debug_context_async(self):
        """DebugContext should work as async context manager."""
        clear_request_id()
        async with DebugContext("async123") as ctx:
            assert ctx.request_id == "async123"
            assert get_request_id() == "async123"

    def test_debug_context_exit_resets_token(self):
        """DebugContext.__exit__ should reset the request ID token."""
        clear_request_id()
        # Set an initial request ID
        set_request_id("initial_id")
        initial_id = get_request_id()

        # Enter a context with a different ID
        with DebugContext("nested_id"):
            assert get_request_id() == "nested_id"
        # After exit, should be back to initial_id
        assert get_request_id() == initial_id

    def test_debug_context_exit_without_enter(self):
        """DebugContext.__exit__ should not fail if called without __enter__."""
        ctx = DebugContext("test_id")
        # _token is None since __enter__ was not called
        assert ctx._token is None
        # Calling __exit__ should not raise
        ctx.__exit__(None, None, None)


class MockView:
    """Simple mock view for testing instrumentation."""

    def __init__(self, name: str):
        self.name = name
        self._call_tool_impl = None

    async def call_tool(self, tool_name: str, args: dict):
        if self._call_tool_impl:
            return await self._call_tool_impl(tool_name, args)
        return {"result": "default"}


class MockClientManager:
    """Simple mock client manager for testing instrumentation."""

    def __init__(self):
        self._call_impl = None

    async def call_upstream_tool(self, server_name: str, tool_name: str, args: dict):
        if self._call_impl:
            return await self._call_impl(server_name, tool_name, args)
        return {"result": "default"}


class TestInstrumentView:
    """Tests for instrument_view function."""

    async def test_instrument_view_wraps_call_tool(self, monkeypatch):
        """instrument_view should wrap view.call_tool."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        view = MockView("test_view")

        async def impl(tool_name, args):
            return {"result": "ok"}

        view._call_tool_impl = impl

        instrument_view(view)

        assert hasattr(view, "_debug_instrumented")
        assert view._debug_instrumented is True

        result = await view.call_tool("my_tool", {"arg": "value"})
        assert result == {"result": "ok"}
        disable_debug()

    async def test_instrument_view_idempotent(self):
        """instrument_view should be idempotent."""
        view = MockView("test_view")

        instrument_view(view)
        first_wrapper = view.call_tool

        instrument_view(view)  # Call again
        second_wrapper = view.call_tool

        # Should be the same wrapper, not doubly wrapped
        assert first_wrapper == second_wrapper

    async def test_instrument_view_disabled_passthrough(self, monkeypatch):
        """Instrumented view should pass through when debug disabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()

        view = MockView("test_view")

        async def impl(tool_name, args):
            return {"result": "direct"}

        view._call_tool_impl = impl

        instrument_view(view)

        result = await view.call_tool("tool", {})
        assert result == {"result": "direct"}

    async def test_instrument_view_logs_slow_call(self, monkeypatch, caplog):
        """Instrumented view should log slow calls."""
        import asyncio

        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def slow_impl(tool_name, args):
            await asyncio.sleep(0.15)  # 150ms > 100ms threshold
            return {"result": "slow"}

        view = MockView("slow_view")
        view._call_tool_impl = slow_impl

        instrument_view(view)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await view.call_tool("slow_tool", {})

        assert result == {"result": "slow"}
        log_text = caplog.text
        assert "SLOW" in log_text or "VIEW_SLOW" in log_text
        disable_debug()

    async def test_instrument_view_logs_exception(self, monkeypatch, caplog):
        """Instrumented view should log exceptions."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def failing_impl(tool_name, args):
            raise RuntimeError("Test failure")

        view = MockView("fail_view")
        view._call_tool_impl = failing_impl

        instrument_view(view)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            with pytest.raises(RuntimeError, match="Test failure"):
                await view.call_tool("fail_tool", {})

        log_text = caplog.text
        assert "FAIL" in log_text or "VIEW_FAIL" in log_text
        disable_debug()


class TestInstrumentClientManager:
    """Tests for instrument_client_manager function."""

    async def test_instrument_client_manager(self, monkeypatch, caplog):
        """instrument_client_manager should wrap call_upstream_tool."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        client_manager = MockClientManager()

        async def impl(server_name, tool_name, args):
            return {"data": "ok"}

        client_manager._call_impl = impl

        instrument_client_manager(client_manager)

        assert hasattr(client_manager, "_debug_instrumented")
        assert client_manager._debug_instrumented is True

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await client_manager.call_upstream_tool(
                "server", "tool", {"arg": "value"}
            )

        assert result == {"data": "ok"}
        log_text = caplog.text
        assert "CLIENT" in log_text
        disable_debug()

    async def test_instrument_client_manager_idempotent(self):
        """instrument_client_manager should be idempotent."""
        client_manager = MockClientManager()

        instrument_client_manager(client_manager)
        first_wrapper = client_manager.call_upstream_tool

        instrument_client_manager(client_manager)
        second_wrapper = client_manager.call_upstream_tool

        assert first_wrapper == second_wrapper

    async def test_instrument_client_manager_disabled(self, monkeypatch):
        """Instrumented client manager should pass through when disabled."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        disable_debug()

        client_manager = MockClientManager()

        async def impl(server_name, tool_name, args):
            return {"data": "direct"}

        client_manager._call_impl = impl

        instrument_client_manager(client_manager)

        result = await client_manager.call_upstream_tool("s", "t", {})
        assert result == {"data": "direct"}

    async def test_instrument_client_manager_logs_slow(self, monkeypatch, caplog):
        """Instrumented client manager should log slow calls."""
        import asyncio

        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def slow_impl(server_name, tool_name, args):
            await asyncio.sleep(0.06)  # 60ms > 50ms threshold
            return {"data": "slow"}

        client_manager = MockClientManager()
        client_manager._call_impl = slow_impl

        instrument_client_manager(client_manager)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            result = await client_manager.call_upstream_tool("s", "t", {})

        assert result == {"data": "slow"}
        log_text = caplog.text
        assert "SLOW" in log_text or "CLIENT_SLOW" in log_text
        disable_debug()

    async def test_instrument_client_manager_logs_exception(self, monkeypatch, caplog):
        """Instrumented client manager should log exceptions."""
        monkeypatch.delenv("MCP_PROXY_DEBUG", raising=False)
        enable_debug()
        configure_debug_logging()

        async def failing_impl(server_name, tool_name, args):
            raise ConnectionError("Connection failed")

        client_manager = MockClientManager()
        client_manager._call_impl = failing_impl

        instrument_client_manager(client_manager)

        with caplog.at_level(logging.DEBUG, logger="mcp_proxy.debug"):
            with pytest.raises(ConnectionError, match="Connection failed"):
                await client_manager.call_upstream_tool("s", "t", {})

        log_text = caplog.text
        assert "FAIL" in log_text or "CLIENT_FAIL" in log_text
        disable_debug()


class MockProxy:
    """Simple mock proxy for testing."""

    def __init__(self):
        self._client_manager = MockClientManager()
        self.views = {}


class MockProxyNoClientManager:
    """Mock proxy without client manager for testing."""

    def __init__(self):
        self.views = {}


class TestInstrumentProxy:
    """Tests for instrument_proxy function."""

    def test_instrument_proxy(self):
        """instrument_proxy should instrument client_manager and views."""
        proxy = MockProxy()
        view1 = MockView("view1")
        view2 = MockView("view2")
        proxy.views = {"view1": view1, "view2": view2}

        instrument_proxy(proxy)

        assert proxy._client_manager._debug_instrumented is True
        assert view1._debug_instrumented is True
        assert view2._debug_instrumented is True

    def test_instrument_proxy_without_client_manager(self):
        """instrument_proxy should work without client manager."""
        proxy = MockProxyNoClientManager()
        view1 = MockView("view1")
        proxy.views = {"view1": view1}

        # Should not raise an error
        instrument_proxy(proxy)

        assert view1._debug_instrumented is True


class TestConfigureDebugLogging:
    """Tests for configure_debug_logging function."""

    def test_configure_debug_logging(self):
        """configure_debug_logging should set up logger."""
        # Get a fresh logger
        test_logger = logging.getLogger("mcp_proxy.debug.test")
        test_logger.handlers.clear()

        # Configure
        configure_debug_logging(logging.DEBUG)

        debug_logger = logging.getLogger("mcp_proxy.debug")
        assert debug_logger.level == logging.DEBUG

    def test_configure_debug_logging_custom_level(self):
        """configure_debug_logging should accept custom level."""
        configure_debug_logging(logging.WARNING)

        debug_logger = logging.getLogger("mcp_proxy.debug")
        assert debug_logger.level == logging.WARNING

        # Reset
        configure_debug_logging(logging.DEBUG)
