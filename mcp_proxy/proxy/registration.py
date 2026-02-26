"""Tool registration utilities for MCP Proxy.

This module provides functions for registering tools on FastMCP instances,
handling both view-based and direct tool registration patterns.
"""

from typing import TYPE_CHECKING, Any, Callable

from fastmcp import FastMCP

from .schema import create_tool_with_schema, transform_args

if TYPE_CHECKING:
    from mcp_proxy.views import ToolView

    from .proxy import MCPProxy


def make_view_wrapper_kwargs(
    view: "ToolView", name: str, param_cfg: dict[str, Any] | None
) -> Callable[..., Any]:
    """Create a kwargs-based wrapper for view tool calls."""

    async def wrapper(**kwargs: Any) -> Any:
        transformed = transform_args(kwargs, param_cfg)
        return await view.call_tool(name, transformed)

    return wrapper


def make_view_wrapper_dict(
    view: "ToolView", name: str, param_cfg: dict[str, Any] | None
) -> Callable[..., Any]:
    """Create a dict-based wrapper for view tool calls."""

    async def wrapper(arguments: dict | None = None) -> Any:
        transformed = transform_args(arguments or {}, param_cfg)
        return await view.call_tool(name, transformed)

    return wrapper


async def _execute_direct_call(
    proxy: "MCPProxy", srv: str, orig_name: str, transformed: dict[str, Any]
) -> Any:
    """Execute a direct call to an upstream tool."""
    if srv not in proxy.config.mcp_servers:
        raise ValueError(f"Server '{srv}' not configured")
    active_client = proxy._active_clients.get(srv)
    if active_client:
        return await active_client.call_tool(orig_name, transformed)
    client = proxy._create_client_from_config(proxy.config.mcp_servers[srv])
    async with client:
        return await client.call_tool(orig_name, transformed)


def make_direct_wrapper_kwargs(
    proxy: "MCPProxy",
    orig_name: str,
    srv: str,
    param_cfg: dict[str, Any] | None,
) -> Callable[..., Any]:
    """Create a kwargs-based wrapper for direct tool calls."""

    async def wrapper(**kwargs: Any) -> Any:
        transformed = transform_args(kwargs, param_cfg)
        return await _execute_direct_call(proxy, srv, orig_name, transformed)

    return wrapper


def make_direct_wrapper_dict(
    proxy: "MCPProxy",
    orig_name: str,
    srv: str,
    param_cfg: dict[str, Any] | None,
) -> Callable[..., Any]:
    """Create a dict-based wrapper for direct tool calls."""

    async def wrapper(arguments: dict | None = None) -> Any:
        transformed = transform_args(arguments or {}, param_cfg)
        return await _execute_direct_call(proxy, srv, orig_name, transformed)

    return wrapper


def register_tool_with_schema(
    mcp: FastMCP,
    tool_name: str,
    tool_desc: str,
    input_schema: dict[str, Any],
    wrapper: Callable[..., Any],
) -> None:
    """Register a tool with an input schema on FastMCP."""
    tool = create_tool_with_schema(
        name=tool_name,
        description=tool_desc,
        input_schema=input_schema,
        fn=wrapper,
    )
    mcp._tool_manager._tools[tool_name] = tool


def register_tool_without_schema(
    mcp: FastMCP,
    tool_name: str,
    tool_desc: str,
    wrapper: Callable[..., Any],
) -> None:
    """Register a tool without an input schema on FastMCP."""
    wrapper.__name__ = tool_name
    wrapper.__doc__ = tool_desc
    mcp.tool(name=tool_name, description=tool_desc)(wrapper)


def register_view_tool(
    mcp: FastMCP,
    view: "ToolView",
    tool_name: str,
    tool_desc: str,
    input_schema: dict[str, Any] | None,
    param_config: dict[str, Any] | None,
) -> None:
    """Register a tool that routes through view.call_tool."""
    if input_schema:
        wrapper = make_view_wrapper_kwargs(view, tool_name, param_config)
        register_tool_with_schema(mcp, tool_name, tool_desc, input_schema, wrapper)
    else:
        wrapper = make_view_wrapper_dict(view, tool_name, param_config)
        register_tool_without_schema(mcp, tool_name, tool_desc, wrapper)


def register_direct_tool(
    mcp: FastMCP,
    proxy: "MCPProxy",
    tool_name: str,
    tool_desc: str,
    input_schema: dict[str, Any] | None,
    original_name: str,
    server: str,
    param_config: dict[str, Any] | None,
) -> None:
    """Register a tool that routes directly through proxy's upstream clients."""
    if input_schema:
        wrapper = make_direct_wrapper_kwargs(proxy, original_name, server, param_config)
        register_tool_with_schema(mcp, tool_name, tool_desc, input_schema, wrapper)
    else:
        wrapper = make_direct_wrapper_dict(proxy, original_name, server, param_config)
        register_tool_without_schema(mcp, tool_name, tool_desc, wrapper)
