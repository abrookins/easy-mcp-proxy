"""Tool fetching and processing functions for MCP Proxy.

This module contains the refactored get_view_tools logic, broken into
smaller focused functions for better maintainability.
"""

from typing import Any

from mcp_proxy.models import ProxyConfig, ToolConfig, ToolViewConfig
from mcp_proxy.proxy.schema import transform_schema
from mcp_proxy.proxy.tool_info import ToolInfo


def _get_param_config(tool_config: ToolConfig | None) -> dict[str, Any] | None:
    """Extract parameter config dict from ToolConfig."""
    if tool_config is None or not tool_config.parameters:
        return None
    return {k: v.model_dump() for k, v in tool_config.parameters.items()}


def _create_tool_info_from_upstream(
    upstream_tool: Any,
    server_name: str,
    tool_config: ToolConfig | None = None,
) -> ToolInfo:
    """Create a ToolInfo from an upstream tool, optionally with config overrides."""
    tool_name = upstream_tool.name
    tool_description = getattr(upstream_tool, "description", "") or ""
    tool_schema = getattr(upstream_tool, "inputSchema", None)

    if tool_config:
        transformed_schema = transform_schema(tool_schema, tool_config)
        param_config = _get_param_config(tool_config)
        exposed_name = tool_config.name if tool_config.name else tool_name
        description = tool_config.description or tool_description
        return ToolInfo(
            name=exposed_name,
            description=description,
            server=server_name,
            input_schema=transformed_schema,
            original_name=tool_name,
            parameter_config=param_config,
        )

    return ToolInfo(
        name=tool_name,
        description=tool_description,
        server=server_name,
        input_schema=tool_schema,
        original_name=tool_name,
    )


def _create_tools_from_aliases(
    tool_config: ToolConfig,
    tool_name: str,
    server_name: str,
    upstream_desc: str,
    transformed_schema: dict[str, Any] | None,
    param_config: dict[str, Any] | None,
) -> list[ToolInfo]:
    """Create ToolInfo objects for all aliases of a tool."""
    tools = []
    for alias in tool_config.aliases:
        tools.append(
            ToolInfo(
                name=alias.name,
                description=alias.description or upstream_desc,
                server=server_name,
                input_schema=transformed_schema,
                original_name=tool_name,
                parameter_config=param_config,
            )
        )
    return tools


def _process_server_with_tools_config(
    server_name: str,
    server_config: Any,
    upstream_tools: list[Any],
) -> list[ToolInfo]:
    """Process a server that has explicit tool configurations."""
    tools: list[ToolInfo] = []
    upstream_by_name = {t.name: t for t in upstream_tools}

    for tool_name, tool_config in server_config.tools.items():
        # Get schema from upstream if available
        upstream_tool = upstream_by_name.get(tool_name)
        tool_schema = (
            getattr(upstream_tool, "inputSchema", None) if upstream_tool else None
        )
        upstream_desc = (
            getattr(upstream_tool, "description", "") if upstream_tool else ""
        )

        # Transform schema based on parameter config
        transformed_schema = transform_schema(tool_schema, tool_config)
        param_config = _get_param_config(tool_config)

        # Handle aliases: if aliases defined, create multiple tools
        if tool_config.aliases:
            tools.extend(
                _create_tools_from_aliases(
                    tool_config,
                    tool_name,
                    server_name,
                    upstream_desc,
                    transformed_schema,
                    param_config,
                )
            )
        else:
            # Single tool (possibly renamed)
            exposed_name = tool_config.name if tool_config.name else tool_name
            description = tool_config.description or upstream_desc
            tools.append(
                ToolInfo(
                    name=exposed_name,
                    description=description,
                    server=server_name,
                    input_schema=transformed_schema,
                    original_name=tool_name,
                    parameter_config=param_config,
                )
            )

    return tools


def _process_server_all_tools(
    server_name: str,
    upstream_tools: list[Any],
) -> list[ToolInfo]:
    """Process a server with no tool config - include ALL upstream tools."""
    tools: list[ToolInfo] = []
    for upstream_tool in upstream_tools:
        tool_name = upstream_tool.name
        tool_description = getattr(upstream_tool, "description", "") or ""
        tool_schema = getattr(upstream_tool, "inputSchema", None)
        tools.append(
            ToolInfo(
                name=tool_name,
                description=tool_description,
                server=server_name,
                input_schema=tool_schema,
                original_name=tool_name,
            )
        )
    return tools


def _process_upstream_tool_with_override(
    upstream_tool: Any,
    server_name: str,
    view_override: ToolConfig | None,
    server_tool_config: ToolConfig | None,
) -> list[ToolInfo]:
    """Process an upstream tool with optional view/server overrides."""
    tools: list[ToolInfo] = []
    tool_name = upstream_tool.name
    tool_description = getattr(upstream_tool, "description", "") or ""
    tool_schema = getattr(upstream_tool, "inputSchema", None)

    # Get effective config (view override takes precedence)
    effective_config = view_override or server_tool_config
    transformed_schema = transform_schema(tool_schema, effective_config)
    param_config = (
        _get_param_config(effective_config) if effective_config else None
    )

    if view_override and view_override.aliases:
        # Handle aliases from view override
        tools.extend(
            _create_tools_from_aliases(
                view_override,
                tool_name,
                server_name,
                tool_description,
                transformed_schema,
                param_config,
            )
        )
    elif view_override:
        exposed_name = view_override.name or tool_name
        description = view_override.description or tool_description
        tools.append(
            ToolInfo(
                name=exposed_name,
                description=description,
                server=server_name,
                input_schema=transformed_schema,
                original_name=tool_name,
                parameter_config=param_config,
            )
        )
    else:
        tools.append(
            ToolInfo(
                name=tool_name,
                description=tool_description,
                server=server_name,
                input_schema=transformed_schema,
                original_name=tool_name,
                parameter_config=param_config,
            )
        )

    return tools


def _process_view_include_all_with_upstream(
    server_name: str,
    upstream_tools: list[Any],
    view_config: ToolViewConfig,
    server_config: Any,
) -> list[ToolInfo]:
    """Process include_all view with actual upstream tools available."""
    tools: list[ToolInfo] = []

    for upstream_tool in upstream_tools:
        tool_name = upstream_tool.name

        # Check if view has override for this tool
        view_override = None
        if server_name in view_config.tools:
            view_override = view_config.tools[server_name].get(tool_name)

        # Get server-level tool config if it exists
        server_tool_config = (
            server_config.tools.get(tool_name) if server_config.tools else None
        )

        tools.extend(
            _process_upstream_tool_with_override(
                upstream_tool,
                server_name,
                view_override,
                server_tool_config,
            )
        )

    return tools


def _process_view_include_all_fallback(
    server_name: str,
    server_config: Any,
    view_config: ToolViewConfig,
) -> list[ToolInfo]:
    """Process include_all view falling back to config-defined tools."""
    tools: list[ToolInfo] = []

    if not server_config.tools:
        return tools

    for tool_name, tool_config in server_config.tools.items():
        view_override = None
        if server_name in view_config.tools:
            view_override = view_config.tools[server_name].get(tool_name)

        # Determine effective config (view override takes precedence)
        effective_config = view_override or tool_config
        transformed_schema = transform_schema(None, effective_config)
        param_config = _get_param_config(effective_config)

        # Handle aliases
        if effective_config.aliases:
            tools.extend(
                _create_tools_from_aliases(
                    effective_config,
                    tool_name,
                    server_name,
                    "",
                    transformed_schema,
                    param_config,
                )
            )
        else:
            exposed_name = effective_config.name or tool_name
            description = effective_config.description or ""
            tools.append(
                ToolInfo(
                    name=exposed_name,
                    description=description,
                    server=server_name,
                    original_name=tool_name,
                    input_schema=transformed_schema,
                    parameter_config=param_config,
                )
            )

    return tools


def _process_view_explicit_tools(
    view_config: ToolViewConfig,
    upstream_tools_cache: dict[str, list[Any]],
    server_configs: dict[str, Any] | None = None,
) -> list[ToolInfo]:
    """Process view with only explicitly listed tools."""
    tools: list[ToolInfo] = []

    for server_name, server_tools in view_config.tools.items():
        # Get upstream tools for this server to find schemas
        upstream_tools = upstream_tools_cache.get(server_name, [])
        upstream_by_name = {t.name: t for t in upstream_tools}

        # Get server config for parameter defaults
        server_config = (
            server_configs.get(server_name) if server_configs else None
        )
        server_tool_configs = (
            server_config.tools if server_config and server_config.tools else {}
        )

        for tool_name, tool_config in server_tools.items():
            # Get schema and description from upstream if available
            upstream_tool = upstream_by_name.get(tool_name)
            if upstream_tool:
                tool_schema = getattr(upstream_tool, "inputSchema", None)
                upstream_desc = getattr(upstream_tool, "description", "") or ""
            else:
                tool_schema = None
                upstream_desc = ""

            # Merge server tool config with view tool config
            # Server config provides defaults, view config can override
            server_tool_config = server_tool_configs.get(tool_name)
            merged_config = _merge_tool_configs(server_tool_config, tool_config)

            # Transform schema based on merged parameter config
            transformed_schema = transform_schema(tool_schema, merged_config)
            param_config = _get_param_config(merged_config)

            # Handle aliases
            if merged_config.aliases:
                tools.extend(
                    _create_tools_from_aliases(
                        merged_config,
                        tool_name,
                        server_name,
                        upstream_desc,
                        transformed_schema,
                        param_config,
                    )
                )
            else:
                exposed_name = merged_config.name if merged_config.name else tool_name
                description = merged_config.description or upstream_desc
                tools.append(
                    ToolInfo(
                        name=exposed_name,
                        description=description,
                        server=server_name,
                        input_schema=transformed_schema,
                        original_name=tool_name,
                        parameter_config=param_config,
                    )
                )

    return tools


def _merge_tool_configs(
    server_config: ToolConfig | None, view_config: ToolConfig
) -> ToolConfig:
    """Merge server tool config with view tool config.

    Server config provides defaults, view config can override.
    """
    if not server_config:
        return view_config

    # Start with server config values, override with view config if set
    merged_params = {}

    # Copy server parameters first
    if server_config.parameters:
        for param_name, param_config in server_config.parameters.items():
            merged_params[param_name] = param_config

    # Override with view parameters
    if view_config.parameters:
        for param_name, param_config in view_config.parameters.items():
            merged_params[param_name] = param_config

    return ToolConfig(
        name=view_config.name or server_config.name,
        description=view_config.description or server_config.description,
        enabled=view_config.enabled if view_config.enabled is not None else server_config.enabled,
        aliases=view_config.aliases or server_config.aliases,
        parameters=merged_params if merged_params else None,
    )

