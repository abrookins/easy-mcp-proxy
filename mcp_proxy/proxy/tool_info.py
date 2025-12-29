"""ToolInfo class for MCP Proxy."""

from typing import Any


class ToolInfo:
    """Simple class to hold tool information."""

    def __init__(
        self,
        name: str,
        description: str = "",
        server: str = "",
        input_schema: dict[str, Any] | None = None,
        original_name: str | None = None,
        parameter_config: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.server = server
        self.input_schema = input_schema
        # original_name is the upstream tool name if this tool was aliased
        self.original_name = original_name if original_name else name
        # parameter_config stores the ParameterConfig for each param
        # (for arg transformation)
        self.parameter_config = parameter_config

    def __repr__(self) -> str:
        return f"ToolInfo(name={self.name!r}, server={self.server!r})"
