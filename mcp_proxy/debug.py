"""Debug instrumentation for MCP Proxy.

Provides timing, logging, and context tracking for MCP tool calls.
Enable via MCP_PROXY_DEBUG=1 environment variable or enable_debug() function.

Features:
- Timing for all tool calls with slow call warnings
- Request ID correlation for tracing related calls
- Structured logging with truncated args/results
- Separate tracking for view-level and upstream-level calls
"""

import contextvars
import functools
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

logger = logging.getLogger("mcp_proxy.debug")

# Context variable for request tracking
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Module-level debug state
_debug_enabled = False

# Configurable thresholds (milliseconds)
SLOW_TOOL_THRESHOLD_MS = 100
SLOW_UPSTREAM_THRESHOLD_MS = 50

T = TypeVar("T", bound=Callable[..., Any])


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled.

    Returns True if either:
    - enable_debug() was called
    - MCP_PROXY_DEBUG env var is set to "1", "true", or "yes"
    """
    if _debug_enabled:
        return True
    env_val = os.environ.get("MCP_PROXY_DEBUG", "").lower()
    return env_val in ("1", "true", "yes")


def enable_debug() -> None:
    """Enable debug logging programmatically."""
    global _debug_enabled
    _debug_enabled = True


def disable_debug() -> None:
    """Disable debug logging programmatically."""
    global _debug_enabled
    _debug_enabled = False


def get_request_id() -> str:
    """Get or create a request ID for the current context."""
    req_id = _request_id.get()
    if req_id is None:
        req_id = str(uuid.uuid4())[:8]
        _request_id.set(req_id)
    return req_id


def set_request_id(req_id: str | None = None) -> str:
    """Set a request ID for the current context. Returns the ID."""
    if req_id is None:
        req_id = str(uuid.uuid4())[:8]
    _request_id.set(req_id)
    return req_id


def clear_request_id() -> None:
    """Clear the request ID for the current context."""
    _request_id.set(None)


@dataclass
class CallMetrics:
    """Metrics collected during a tool call."""

    tool_name: str
    view_name: str | None = None
    server_name: str | None = None
    start_time: float = field(default_factory=time.perf_counter)
    end_time: float | None = None
    success: bool = True
    error: str | None = None
    request_id: str | None = None

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        if self.end_time is None:
            return (time.perf_counter() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def complete(self, success: bool = True, error: str | None = None) -> None:
        """Mark the call as complete."""
        self.end_time = time.perf_counter()
        self.success = success
        self.error = error


def _truncate(value: str, max_len: int = 100) -> str:
    """Truncate a string with ellipsis if too long."""
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _format_value(value: Any, max_len: int = 100) -> str:
    """Format a value for logging, truncating if needed."""
    if value is None:
        return "None"
    if isinstance(value, str):
        return _truncate(repr(value), max_len)
    if isinstance(value, (dict, list)):
        try:
            s = json.dumps(value, default=str)
            return _truncate(s, max_len)
        except (TypeError, ValueError):
            return _truncate(str(value), max_len)
    return _truncate(str(value), max_len)


def _format_args(args: dict[str, Any], max_len: int = 100) -> str:
    """Format function arguments for logging."""
    if not args:
        return "{}"
    parts = []
    for k, v in args.items():
        parts.append(f"{k}={_format_value(v, 50)}")
    result = "{" + ", ".join(parts) + "}"
    return _truncate(result, max_len)


def _summarize_result(result: Any) -> str:
    """Create a brief summary of a tool result."""
    if result is None:
        return "None"
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        if len(result) > 5:
            return f"dict({len(result)} keys: {keys}...)"
        return f"dict({keys})"
    if isinstance(result, list):
        return f"list({len(result)} items)"
    if isinstance(result, str):
        return f"str({len(result)} chars)"
    if hasattr(result, "content"):
        return f"CallToolResult({len(getattr(result, 'content', []))} items)"
    return type(result).__name__


def timed_tool(
    fn: T,
    *,
    tool_name: str | None = None,
    view_name: str | None = None,
    server_name: str | None = None,
) -> T:
    """Decorator that wraps a tool function with timing and logging.

    Args:
        fn: The async function to wrap
        tool_name: Override the tool name (defaults to fn.__name__)
        view_name: The view this tool belongs to
        server_name: The upstream server name

    Returns:
        Wrapped async function with timing instrumentation
    """
    name = tool_name or fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_debug_enabled():
            return await fn(*args, **kwargs)

        req_id = get_request_id()
        metrics = CallMetrics(
            tool_name=name,
            view_name=view_name,
            server_name=server_name,
            request_id=req_id,
        )

        # Log call start
        args_str = _format_args(kwargs)
        context_parts = [f"req={req_id}"]
        if view_name:
            context_parts.append(f"view={view_name}")
        if server_name:
            context_parts.append(f"server={server_name}")
        context_str = " ".join(context_parts)

        logger.debug(f"CALL [{context_str}] {name}({args_str})")

        try:
            result = await fn(*args, **kwargs)
            metrics.complete(success=True)

            # Log result with appropriate level based on duration
            elapsed = metrics.elapsed_ms
            result_summary = _summarize_result(result)

            if elapsed > SLOW_TOOL_THRESHOLD_MS:
                logger.warning(
                    f"SLOW [{context_str}] {name} completed in {elapsed:.1f}ms "
                    f"-> {result_summary}"
                )
            else:
                logger.debug(
                    f"DONE [{context_str}] {name} completed in {elapsed:.1f}ms "
                    f"-> {result_summary}"
                )

            return result

        except Exception as e:
            metrics.complete(success=False, error=str(e))
            elapsed = metrics.elapsed_ms
            logger.error(
                f"FAIL [{context_str}] {name} failed in {elapsed:.1f}ms: "
                f"{type(e).__name__}: {e}"
            )
            raise

    return wrapper  # type: ignore[return-value]


def timed_upstream_call(
    fn: T,
    *,
    server_name: str | None = None,
) -> T:
    """Decorator for upstream client calls with lower threshold.

    Similar to timed_tool but uses SLOW_UPSTREAM_THRESHOLD_MS.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_debug_enabled():
            return await fn(*args, **kwargs)

        req_id = get_request_id()
        start = time.perf_counter()

        # Extract tool_name from args if possible
        tool_name = kwargs.get("tool_name", args[1] if len(args) > 1 else "?")
        srv = server_name or kwargs.get("server_name", args[0] if args else "?")

        logger.debug(f"UPSTREAM [req={req_id}] {srv}.{tool_name} starting")

        try:
            result = await fn(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000

            if elapsed > SLOW_UPSTREAM_THRESHOLD_MS:
                logger.warning(
                    f"UPSTREAM_SLOW [req={req_id}] {srv}.{tool_name} "
                    f"completed in {elapsed:.1f}ms"
                )
            else:
                logger.debug(
                    f"UPSTREAM_DONE [req={req_id}] {srv}.{tool_name} "
                    f"completed in {elapsed:.1f}ms"
                )

            return result

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                f"UPSTREAM_FAIL [req={req_id}] {srv}.{tool_name} "
                f"failed in {elapsed:.1f}ms: {e}"
            )
            raise

    return wrapper  # type: ignore[return-value]


class DebugContext:
    """Context manager for debug instrumentation of a request.

    Usage:
        async with DebugContext("my-request"):
            await tool_view.call_tool("my_tool", {})
    """

    def __init__(self, request_id: str | None = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "DebugContext":
        self._token = _request_id.set(self.request_id)
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token:
            _request_id.reset(self._token)

    async def __aenter__(self) -> "DebugContext":
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        self.__exit__(*args)


def instrument_view(view: Any) -> None:
    """Instrument a ToolView's call_tool method with debug logging.

    This wraps the view's call_tool method to add timing and logging
    when debug mode is enabled. The wrapper is idempotent - calling
    this multiple times on the same view is safe.

    Args:
        view: A ToolView instance to instrument
    """
    if hasattr(view, "_debug_instrumented"):
        return  # Already instrumented

    original_call_tool = view.call_tool

    @functools.wraps(original_call_tool)
    async def instrumented_call_tool(
        tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        if not is_debug_enabled():
            return await original_call_tool(tool_name, args)

        # Set up request context if not already set
        req_id = get_request_id()
        metrics = CallMetrics(
            tool_name=tool_name,
            view_name=view.name,
            request_id=req_id,
        )

        args_str = _format_args(args)
        logger.debug(
            f"VIEW_CALL [req={req_id} view={view.name}] {tool_name}({args_str})"
        )

        try:
            result = await original_call_tool(tool_name, args)
            metrics.complete(success=True)
            elapsed = metrics.elapsed_ms
            result_summary = _summarize_result(result)

            if elapsed > SLOW_TOOL_THRESHOLD_MS:
                logger.warning(
                    f"VIEW_SLOW [req={req_id} view={view.name}] {tool_name} "
                    f"completed in {elapsed:.1f}ms -> {result_summary}"
                )
            else:
                logger.debug(
                    f"VIEW_DONE [req={req_id} view={view.name}] {tool_name} "
                    f"completed in {elapsed:.1f}ms -> {result_summary}"
                )

            return result

        except Exception as e:
            metrics.complete(success=False, error=str(e))
            elapsed = metrics.elapsed_ms
            logger.error(
                f"VIEW_FAIL [req={req_id} view={view.name}] {tool_name} "
                f"failed in {elapsed:.1f}ms: {type(e).__name__}: {e}"
            )
            raise

    view.call_tool = instrumented_call_tool
    view._debug_instrumented = True


def instrument_client_manager(client_manager: Any) -> None:
    """Instrument a ClientManager's call_upstream_tool method.

    Args:
        client_manager: A ClientManager instance to instrument
    """
    if hasattr(client_manager, "_debug_instrumented"):
        return

    original_call = client_manager.call_upstream_tool

    @functools.wraps(original_call)
    async def instrumented_call(
        server_name: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        if not is_debug_enabled():
            return await original_call(server_name, tool_name, args)

        req_id = get_request_id()
        start = time.perf_counter()

        logger.debug(f"CLIENT_CALL [req={req_id}] {server_name}.{tool_name} starting")

        try:
            result = await original_call(server_name, tool_name, args)
            elapsed = (time.perf_counter() - start) * 1000

            if elapsed > SLOW_UPSTREAM_THRESHOLD_MS:
                logger.warning(
                    f"CLIENT_SLOW [req={req_id}] {server_name}.{tool_name} "
                    f"completed in {elapsed:.1f}ms"
                )
            else:
                logger.debug(
                    f"CLIENT_DONE [req={req_id}] {server_name}.{tool_name} "
                    f"completed in {elapsed:.1f}ms"
                )

            return result

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                f"CLIENT_FAIL [req={req_id}] {server_name}.{tool_name} "
                f"failed in {elapsed:.1f}ms: {e}"
            )
            raise

    client_manager.call_upstream_tool = instrumented_call
    client_manager._debug_instrumented = True


def instrument_proxy(proxy: Any) -> None:
    """Instrument an MCPProxy instance with debug logging.

    This instruments:
    - All views' call_tool methods
    - The client manager's call_upstream_tool method

    Args:
        proxy: An MCPProxy instance to instrument
    """
    # Instrument client manager
    if hasattr(proxy, "_client_manager"):
        instrument_client_manager(proxy._client_manager)

    # Instrument all views
    for view in proxy.views.values():
        instrument_view(view)


def configure_debug_logging(level: int = logging.DEBUG) -> None:
    """Configure logging for debug output.

    Sets up the mcp_proxy.debug logger with appropriate formatting.
    Call this during application startup if you want debug output.

    Args:
        level: Logging level for the debug logger
    """
    debug_logger = logging.getLogger("mcp_proxy.debug")
    debug_logger.setLevel(level)

    if not debug_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        debug_logger.addHandler(handler)
