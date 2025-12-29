"""Hook system for MCP Proxy."""

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable


@dataclass
class ToolCallContext:
    """Context passed to hooks during tool execution."""

    view_name: str
    tool_name: str
    upstream_server: str


@dataclass
class HookResult:
    """Result from a hook execution."""

    args: dict[str, Any] | None = None
    result: Any | None = None
    abort: bool = False
    abort_reason: str | None = None


def load_hook(dotted_path: str) -> Callable:
    """Load a hook function from a dotted module path."""
    module_path, func_name = dotted_path.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, func_name)


async def execute_pre_call(
    hook: Callable, args: dict[str, Any], context: ToolCallContext
) -> HookResult:
    """Execute a pre-call hook."""
    return await hook(args, context)


async def execute_post_call(
    hook: Callable, result: Any, args: dict[str, Any], context: ToolCallContext
) -> HookResult:
    """Execute a post-call hook."""
    return await hook(result, args, context)
