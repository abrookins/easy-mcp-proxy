"""Configuration models for MCP Proxy."""

from pydantic import BaseModel, RootModel


class ToolConfig(BaseModel):
    """Configuration for a single tool."""

    name: str | None = None
    description: str | None = None
    enabled: bool = True


class HooksConfig(BaseModel):
    """Configuration for pre/post call hooks."""

    pre_call: str | None = None
    post_call: str | None = None


class ToolViewConfig(BaseModel):
    """Configuration for a tool view."""

    description: str | None = None
    exposure_mode: str = "direct"
    tools: dict[str, dict[str, ToolConfig]] = {}
    hooks: HooksConfig | None = None
    include_all: bool = False


class ServerToolsConfig(RootModel[dict[str, ToolConfig]]):
    """Maps tool names to their configurations for a server."""

    pass


class UpstreamServerConfig(BaseModel):
    """Configuration for an upstream MCP server."""

    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] = {}
    headers: dict[str, str] = {}


class ProxyConfig(BaseModel):
    """Root configuration for the MCP proxy."""

    mcp_servers: dict[str, UpstreamServerConfig] = {}
    tool_views: dict[str, ToolViewConfig] = {}

