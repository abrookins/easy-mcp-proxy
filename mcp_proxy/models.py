"""Configuration models for MCP Proxy."""

from pydantic import BaseModel, ConfigDict, RootModel


class ToolConfig(BaseModel):
    """Configuration for a single tool."""

    name: str | None = None
    description: str | None = None
    enabled: bool = True


class HooksConfig(BaseModel):
    """Configuration for pre/post call hooks."""

    pre_call: str | None = None
    post_call: str | None = None


class CompositeToolConfig(BaseModel):
    """Configuration for a composite (parallel) tool."""

    description: str = ""
    inputs: dict[str, dict] = {}
    parallel: dict[str, dict] = {}


class ToolViewConfig(BaseModel):
    """Configuration for a tool view."""

    description: str | None = None
    exposure_mode: str = "direct"
    tools: dict[str, dict[str, ToolConfig]] = {}
    hooks: HooksConfig | None = None
    include_all: bool = False
    custom_tools: list[dict] = []
    composite_tools: dict[str, CompositeToolConfig] = {}


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
    tools: dict[str, ToolConfig] | None = None


class ProxyConfig(BaseModel):
    """Root configuration for the MCP proxy."""

    model_config = ConfigDict(extra="forbid")

    mcp_servers: dict[str, UpstreamServerConfig] = {}
    tool_views: dict[str, ToolViewConfig] = {}

