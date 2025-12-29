"""Custom tools for MCP Proxy."""

import inspect
from functools import wraps
from typing import Any, Callable, get_type_hints


def _python_type_to_json_type(python_type: type) -> str:
    """Convert Python type to JSON schema type."""
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    return type_map.get(python_type, "string")


def _infer_schema(func: Callable) -> dict:
    """Infer JSON schema from function type hints."""
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx", "context"):
            continue

        param_type = hints.get(param_name, str)
        properties[param_name] = {"type": _python_type_to_json_type(param_type)}

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


class ProxyContext:
    """Context injected into custom tools for calling upstream tools."""

    def __init__(
        self,
        call_tool_fn: Callable | None = None,
        available_tools: list[str] | None = None,
    ):
        self._call_tool_fn = call_tool_fn
        self.available_tools = available_tools or []

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Call an upstream tool by name."""
        if self._call_tool_fn is None:
            raise RuntimeError("No call_tool_fn configured")
        return await self._call_tool_fn(tool_name, **kwargs)

    def list_tools(self) -> list[str]:
        """List available upstream tools."""
        return self.available_tools


def load_custom_tool(dotted_path: str) -> Callable:
    """Load a custom tool from a dotted module path."""
    from importlib import import_module

    module_path, func_name = dotted_path.rsplit(".", 1)
    module = import_module(module_path)
    func = getattr(module, func_name)

    if not getattr(func, "_is_custom_tool", False):
        raise ValueError(f"{dotted_path} is not a custom tool")

    return func


def custom_tool(name: str, description: str) -> Callable:
    """Decorator to mark a function as a custom tool."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            return await func(*args, **kwargs)

        wrapper._is_custom_tool = True
        wrapper._tool_name = name
        wrapper._tool_description = description
        wrapper._input_schema = _infer_schema(func)

        return wrapper

    return decorator
