"""Configuration models for MCP Proxy."""

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel


class AliasConfig(BaseModel):
    """Configuration for a tool alias."""

    name: str
    description: str | None = None


class ParameterConfig(BaseModel):
    """Configuration for a tool parameter.

    Allows hiding parameters (with default values), renaming them,
    or overriding their descriptions.
    """

    hidden: bool = False
    default: Any | None = None
    rename: str | None = None
    description: str | None = None


class ToolConfig(BaseModel):
    """Configuration for a single tool.

    Supports either a single rename (via `name`) or multiple aliases (via `aliases`).
    If `aliases` is provided, it takes precedence over `name`.

    The `parameters` field allows customizing individual parameters:
    - Hide parameters and inject fixed default values
    - Rename parameters to more domain-appropriate names
    - Override parameter descriptions
    """

    name: str | None = None
    description: str | None = None
    enabled: bool = True
    aliases: list[AliasConfig] | None = None
    parameters: dict[str, ParameterConfig] | None = None


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
    cwd: str | None = None  # Working directory for stdio servers
    url: str | None = None
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    tools: dict[str, ToolConfig] | None = None


class ProxyConfig(BaseModel):
    """Root configuration for the MCP proxy.

    Note: Authentication is configured via environment variables for Auth0.
    See mcp_proxy.auth module for details.
    """

    model_config = ConfigDict(extra="forbid")

    mcp_servers: dict[str, UpstreamServerConfig] = {}
    tool_views: dict[str, ToolViewConfig] = {}
