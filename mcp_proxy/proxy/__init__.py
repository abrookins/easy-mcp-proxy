"""MCP Proxy package."""

from mcp_proxy.utils import expand_env_vars

from .proxy import MCPProxy
from .schema import transform_args, transform_schema
from .tool_info import ToolInfo

# Keep old names for backward compatibility with tests
_transform_schema = transform_schema
_transform_args = transform_args

__all__ = [
    "MCPProxy",
    "ToolInfo",
    "transform_schema",
    "transform_args",
    "_transform_schema",
    "_transform_args",
    "expand_env_vars",
]
