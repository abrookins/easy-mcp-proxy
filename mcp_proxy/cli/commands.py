"""Main CLI commands for mcp-proxy."""

import json
from typing import Any

import click
from rapidfuzz import fuzz, process

from mcp_proxy.cli.utils import (
    config_option,
    get_config_path,
    run_async,
)
from mcp_proxy.config import load_config


@click.command()
@config_option()
def servers(config: str | None):
    """List configured upstream servers."""
    cfg = load_config(str(get_config_path(config)))
    for name in cfg.mcp_servers:
        click.echo(name)


@click.command()
@config_option()
@click.option("--server", "-s", default=None, help="Filter by server name")
@click.option("--view", "-v", default=None, help="Inspect one exposed tool view")
@click.option("--verbose", is_flag=True, help="Show canonical tool metadata")
@click.option("--json", "as_json", is_flag=True, help="Output stable JSON")
def tools(
    config: str | None,
    server: str | None,
    view: str | None,
    verbose: bool,
    as_json: bool,
):
    """List all tools from configured servers."""
    cfg = load_config(str(get_config_path(config)))

    if view is None and not verbose and not as_json:
        configured_names: set[str] = set()

        # Keep the original, configuration-only output as the fast default.
        for server_name, server_config in cfg.mcp_servers.items():
            if server and server_name != server:
                continue
            if server_config.tools:
                configured_names.update(
                    f"{server_name}.{tool_name}" for tool_name in server_config.tools
                )

        for view_config in cfg.tool_views.values():
            for server_name, tools_dict in view_config.tools.items():
                if server and server_name != server:
                    continue
                configured_names.update(
                    f"{server_name}.{tool_name}" for tool_name in tools_dict
                )

        for name in sorted(configured_names):
            click.echo(name)
        return

    from mcp_proxy.proxy import MCPProxy

    if view is not None:
        _require_name("view", view, sorted(cfg.tool_views), as_json)
    if server is not None:
        _require_name("server", server, sorted(cfg.mcp_servers), as_json)

    proxy = MCPProxy(cfg)
    raw_tools, errors = run_async(_fetch_cli_tools(proxy, cfg))
    if errors:
        _fail_connection(errors, as_json)

    canonical_tools = proxy.get_view_tools(view)
    if server is not None:
        canonical_tools = [tool for tool in canonical_tools if tool.server == server]
    metadata = [
        tool.to_metadata(include_schema=verbose)
        for tool in sorted(canonical_tools, key=lambda item: (item.name, item.server))
    ]

    if as_json:
        payload: dict[str, Any] = {"tools": metadata}
        payload["view"] = view or "default"
        click.echo(json.dumps(payload, sort_keys=True))
        return

    for item in metadata:
        if not verbose:
            prefix = f"{item['server']}." if item["server"] else ""
            click.echo(f"{prefix}{item['name']}")
            continue
        _output_exposed_tool(item, include_schema=True)


def _suggest(name: str, choices: list[str]) -> str | None:
    """Return a conservative fuzzy suggestion from deterministic choices."""
    match = process.extractOne(name, choices, scorer=fuzz.ratio)
    if match is None or match[1] < 70:
        return None
    return str(match[0])


def _fail(payload: dict[str, Any], as_json: bool) -> None:
    """Emit a stable CLI error and exit with status one."""
    if as_json:
        click.echo(json.dumps(payload, sort_keys=True))
    else:
        message = str(payload["message"])
        if suggestion := payload.get("did_you_mean"):
            message += f" Did you mean '{suggestion}'?"
        click.echo(f"Error: {message}", err=True)
    raise click.exceptions.Exit(1)


def _require_name(kind: str, name: str, choices: list[str], as_json: bool) -> None:
    """Validate a configured view or server name with an optional hint."""
    if name in choices:
        return
    payload: dict[str, Any] = {
        "error": f"unknown_{kind}",
        "message": f"{kind.title()} '{name}' not found.",
        f"available_{kind}_names": choices,
    }
    if suggestion := _suggest(name, choices):
        payload["did_you_mean"] = suggestion
    _fail(payload, as_json)


async def _fetch_cli_tools(
    proxy: Any, cfg: Any
) -> tuple[dict[str, list], dict[str, str]]:
    """Fetch raw upstream metadata once and refresh the canonical registry."""
    raw_tools: dict[str, list] = {}
    errors: dict[str, str] = {}
    for server_name in sorted(cfg.mcp_servers):
        try:
            client = await proxy._create_client(server_name)
            async with client:
                discovered = list(await client.list_tools())
            proxy._upstream_tools[server_name] = discovered
            raw_tools[server_name] = discovered
        except Exception as exc:
            errors[server_name] = str(exc)
    proxy._refresh_tool_registries()
    return raw_tools, errors


def _fail_connection(errors: dict[str, str], as_json: bool) -> None:
    """Report upstream failures separately from lookup failures."""
    servers = sorted(errors)
    _fail(
        {
            "error": "connection_error",
            "message": "Could not inspect upstream tool metadata.",
            "servers": {name: errors[name] for name in servers},
        },
        as_json,
    )


def _output_exposed_tool(metadata: dict[str, Any], include_schema: bool) -> None:
    """Render one canonical exposed metadata record for a human."""
    accepted = metadata["accepted_parameter_names"]
    click.echo(f"Tool: {metadata['name']}")
    click.echo(f"Description: {metadata['description'] or 'N/A'}")
    click.echo(f"Server: {metadata['server'] or 'custom'}")
    click.echo(f"Original name: {metadata['original_name']}")
    click.echo(f"Accepted parameters: {', '.join(accepted) if accepted else 'none'}")
    dry_run = "yes" if metadata["supports_dry_run"] else "no"
    click.echo(f"Dry-run supported: {dry_run}")
    if include_schema:
        click.echo(f"Input schema: {json.dumps(metadata['inputSchema'], indent=2)}")


def _output_tool_schema(tool_name: str, tool_schema: dict | None, as_json: bool):
    """Output schema for a single tool."""
    import json as json_module

    if as_json:
        if tool_schema:
            click.echo(json_module.dumps({"tool": tool_name, "schema": tool_schema}))
        else:
            click.echo(json_module.dumps({"tool": tool_name, "error": "not found"}))
    else:
        if tool_schema:
            click.echo(f"Tool: {tool_name}")
            click.echo(f"Description: {tool_schema.get('description', 'N/A')}")
            schema = tool_schema.get("inputSchema", {})
            properties = schema.get("properties", {})
            accepted = sorted(properties) if isinstance(properties, dict) else []
            dry_run = (
                properties.get("dry_run") if isinstance(properties, dict) else None
            )
            supports_dry_run = (
                isinstance(dry_run, dict) and dry_run.get("type") == "boolean"
            )
            click.echo(
                f"Accepted parameters: {', '.join(accepted) if accepted else 'none'}"
            )
            click.echo(f"Dry-run supported: {'yes' if supports_dry_run else 'no'}")
            params = json_module.dumps(schema, indent=2)
            click.echo(f"Parameters: {params}")
        else:
            parts = tool_name.split(".", 1)
            click.echo(f"Tool '{parts[1]}' not found on server '{parts[0]}'")


def _output_server_tools(server_name: str, tools_list: list, as_json: bool):
    """Output tools for a single server."""
    import json as json_module

    if as_json:
        click.echo(json_module.dumps({"server": server_name, "tools": tools_list}))
    else:
        click.echo(f"Server: {server_name}")
        click.echo(f"Tools ({len(tools_list)}):")
        for t in tools_list:
            click.echo(f"  - {t['name']}: {t.get('description', 'No description')}")


def _output_connection_error(
    name: str, error: str, as_json: bool, is_tool: bool = False
):
    """Output a connection error."""
    import json as json_module

    key = "tool" if is_tool else "server"
    if as_json:
        click.echo(json_module.dumps({key: name, "error": error}))
    else:
        click.echo(f"Error connecting to {name}: {error}", err=True)


@click.command()
@click.argument("tool_name", required=False)
@config_option()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--server", "-s", default=None, help="Filter by server name")
@click.option("--view", "-v", default=None, help="Inspect an exposed tool view")
def schema(
    tool_name: str | None,
    config: str | None,
    as_json: bool,
    server: str | None,
    view: str | None,
):
    """Show schema for a specific tool or all tools."""
    import json as json_module

    from mcp_proxy.proxy import MCPProxy

    cfg = load_config(str(get_config_path(config)))
    proxy = MCPProxy(cfg)

    if view is not None and server is not None:
        _fail(
            {
                "error": "invalid_options",
                "message": "--view and --server cannot be used together.",
            },
            as_json,
        )

    if view is not None:
        _require_name("view", view, sorted(cfg.tool_views), as_json)
        _, errors = run_async(_fetch_cli_tools(proxy, cfg))
        if errors:
            _fail_connection(errors, as_json)
        exposed = sorted(proxy.get_view_tools(view), key=lambda item: item.name)
        if tool_name is None:
            metadata = [tool.to_metadata(include_schema=True) for tool in exposed]
            if as_json:
                click.echo(
                    json_module.dumps({"view": view, "tools": metadata}, sort_keys=True)
                )
            else:
                for item in metadata:
                    _output_exposed_tool(item, include_schema=False)
            return

        tool = next((item for item in exposed if item.name == tool_name), None)
        if tool is None:
            choices = [item.name for item in exposed]
            payload: dict[str, Any] = {
                "error": "unknown_tool",
                "message": f"Tool '{tool_name}' not found in view '{view}'.",
                "tool": tool_name,
                "view": view,
                "available_tool_names": choices,
            }
            if suggestion := _suggest(tool_name, choices):
                payload["did_you_mean"] = suggestion
            _fail(payload, as_json)
        metadata = tool.to_metadata(include_schema=True)
        if as_json:
            click.echo(json_module.dumps(metadata, sort_keys=True))
        else:
            _output_exposed_tool(metadata, include_schema=True)
        return

    async def fetch_schemas():
        """Fetch schemas from upstream servers and custom tools."""
        all_tools = {}

        for server_name, server_config in cfg.mcp_servers.items():
            try:
                client = await proxy._create_client(server_name)
                async with client:
                    tools_list = await client.list_tools()
                    # Filter tools based on config's tool constraints
                    allowed_tools = (
                        server_config.tools.keys() if server_config.tools else None
                    )
                    all_tools[server_name] = [
                        {
                            "name": t.name,
                            "description": getattr(t, "description", ""),
                            "inputSchema": getattr(t, "inputSchema", {}),
                        }
                        for t in tools_list
                        if allowed_tools is None or t.name in allowed_tools
                    ]
            except Exception as e:
                all_tools[server_name] = {"error": str(e)}

        # Include custom tools from views
        for view_name, view in proxy.views.items():
            if view.custom_tools:
                custom_tools_list = []
                for name, tool_fn in view.custom_tools.items():
                    desc = getattr(tool_fn, "_tool_description", "")
                    schema = getattr(tool_fn, "_input_schema", {})
                    custom_tools_list.append(
                        {
                            "name": name,
                            "description": desc,
                            "inputSchema": schema,
                        }
                    )
                if custom_tools_list:  # pragma: no branch
                    key = f"custom ({view_name})"
                    all_tools[key] = custom_tools_list

        return all_tools

    if tool_name:
        # Parse tool_name as server.tool
        if "." not in tool_name:
            click.echo("Error: tool name must be in format 'server.tool'", err=True)
            raise SystemExit(1)

        server_name, tool = tool_name.split(".", 1)

        _require_name("server", server_name, sorted(cfg.mcp_servers), as_json)

        all_tools = run_async(fetch_schemas())
        server_tools = all_tools.get(server_name, [])

        if isinstance(server_tools, dict) and "error" in server_tools:
            _output_connection_error(
                server_name, server_tools["error"], as_json, is_tool=True
            )
            raise SystemExit(1)

        tool_schema = next((t for t in server_tools if t["name"] == tool), None)
        if tool_schema is None:
            choices = sorted(item["name"] for item in server_tools)
            payload: dict[str, Any] = {
                "error": "not found",
                "error_code": "unknown_tool",
                "message": f"Tool '{tool}' not found on server '{server_name}'.",
                "tool": tool,
                "server": server_name,
                "available_tool_names": choices,
            }
            if suggestion := _suggest(tool, choices):
                payload["did_you_mean"] = suggestion
            _fail(payload, as_json)
        _output_tool_schema(tool_name, tool_schema, as_json)

    elif server:
        _require_name("server", server, sorted(cfg.mcp_servers), as_json)

        all_tools = run_async(fetch_schemas())
        server_tools = all_tools.get(server, [])

        if isinstance(server_tools, dict) and "error" in server_tools:
            _output_connection_error(server, server_tools["error"], as_json)
            raise SystemExit(1)

        _output_server_tools(server, server_tools, as_json)
    else:
        # List all schemas
        all_tools = run_async(fetch_schemas())
        if as_json:
            click.echo(json_module.dumps({"tools": all_tools}))
        else:
            for server_name, tools_list in all_tools.items():
                if isinstance(tools_list, dict) and "error" in tools_list:
                    click.echo(f"{server_name}: error - {tools_list['error']}")
                else:
                    click.echo(f"{server_name}: {len(tools_list)} tools")
                    for t in tools_list:
                        click.echo(f"  - {t['name']}")


@click.command()
@config_option()
@click.option(
    "--check-connections", "-C", is_flag=True, help="Check upstream server connections"
)
def validate(config: str | None, check_connections: bool):
    """Validate configuration file."""
    from mcp_proxy.config import validate_config
    from mcp_proxy.proxy import MCPProxy

    try:
        cfg = load_config(str(get_config_path(config)))
        errors = validate_config(cfg)
        if errors:
            for error in errors:
                click.echo(f"Error: {error}", err=True)
            raise SystemExit(1)
        click.echo("Configuration is valid.")

        if check_connections:
            click.echo("\nChecking upstream connections...")
            proxy = MCPProxy(cfg)

            async def check_all():
                results = {}
                for server_name in cfg.mcp_servers:
                    try:
                        client = await proxy._create_client(server_name)
                        async with client:
                            tools_list = await client.list_tools()
                            results[server_name] = {
                                "status": "connected",
                                "tools": len(tools_list),
                            }
                    except Exception as e:
                        results[server_name] = {"status": "failed", "error": str(e)}
                return results

            results = run_async(check_all())
            all_ok = True
            for server_name, result in results.items():
                if result["status"] == "connected":
                    click.echo(f"  {server_name}: connected ({result['tools']} tools)")
                else:
                    click.echo(
                        f"  {server_name}: connection failed - {result['error']}",
                        err=True,
                    )
                    all_ok = False

            if not all_ok:
                raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@click.command()
@config_option()
@click.option(
    "--transport",
    "-t",
    default="stdio",
    type=click.Choice(["stdio", "http"]),
    help="Transport type",
)
@click.option("--port", "-p", default=8000, type=int, help="Port for HTTP transport")
@click.option(
    "--env-file",
    "-e",
    default=".env",
    type=click.Path(),
    help="Path to .env file (default: .env)",
)
@click.option(
    "--access-log/--no-access-log",
    default=True,
    help="Enable/disable access logging (HTTP only, default: enabled)",
)
@click.option(
    "--debug/--no-debug",
    default=False,
    help="Enable debug logging for tool calls (timing, args, results)",
)
def serve(
    config: str | None,
    transport: str,
    port: int,
    env_file: str,
    access_log: bool,
    debug: bool,
):  # pragma: no cover
    """Start the MCP proxy server."""
    import logging
    import os

    from dotenv import load_dotenv

    from mcp_proxy.debug import configure_file_logging
    from mcp_proxy.proxy import MCPProxy

    # Load environment variables from .env file
    load_dotenv(env_file)

    log_file = os.environ.get("MCP_PROXY_LOG_FILE")
    if log_file:
        level_name = os.environ.get("MCP_PROXY_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        configure_file_logging(log_file, level=level)

    cfg = load_config(str(get_config_path(config)))
    proxy = MCPProxy(cfg)

    # Enable debug instrumentation if requested
    if debug:
        proxy.enable_debug()

    proxy.run(transport=transport, port=port, access_log=access_log)


@click.command()
@click.argument("tool_name")
@config_option()
@click.option("--arg", "-a", multiple=True, help="Tool arguments as key=value")
def call(tool_name: str, config: str | None, arg: tuple[str, ...]):
    """Call a specific tool."""
    import json as json_module

    from mcp_proxy.proxy import MCPProxy

    cfg = load_config(str(get_config_path(config)))

    # Parse tool_name as server.tool
    if "." not in tool_name:
        click.echo("Error: tool name must be in format 'server.tool'", err=True)
        raise SystemExit(1)

    server_name, tool = tool_name.split(".", 1)

    if server_name not in cfg.mcp_servers:
        click.echo(f"Error: server '{server_name}' not found", err=True)
        raise SystemExit(1)

    # Parse arguments - try to parse numeric values
    args = {}
    for a in arg:
        if "=" in a:
            k, v = a.split("=", 1)
            # Try to parse as number
            try:
                args[k] = int(v)
            except ValueError:
                try:
                    args[k] = float(v)
                except ValueError:
                    args[k] = v

    async def call_tool():
        """Call the tool on the upstream server."""
        proxy = MCPProxy(cfg)
        client = await proxy._create_client(server_name)
        async with client:
            return await client.call_tool(tool, args)

    try:
        result = run_async(call_tool())
        click.echo(f"Calling {tool_name} with args: {json_module.dumps(args)}")
        # Handle result content
        if hasattr(result, "content"):
            for content in result.content:
                if hasattr(content, "text"):
                    click.echo(f"Result: {content.text}")
                else:
                    click.echo(f"Result: {content}")
        else:
            click.echo(f"Result: {json_module.dumps(result, default=str)}")
    except Exception as e:
        click.echo(f"Error calling {tool_name}: {e}", err=True)
        raise SystemExit(1)


@click.command("config")
@config_option()
@click.option("--resolved", is_flag=True, help="Show config with env vars resolved")
def config_cmd(config: str | None, resolved: bool):
    """Show configuration."""
    import yaml

    config_path = get_config_path(config)
    cfg = load_config(str(config_path))
    if resolved:
        click.echo(yaml.dump(cfg.model_dump(), default_flow_style=False))
    else:
        with open(config_path) as f:
            click.echo(f.read())


@click.command()
@click.argument("what", type=click.Choice(["hooks", "config"]))
def init(what: str):
    """Generate example files."""
    examples = {
        "hooks": '''"""Example hooks for MCP Proxy."""

from mcp_proxy.hooks import HookResult, ToolCallContext


async def pre_call(args: dict, context: ToolCallContext) -> HookResult:
    """Pre-call hook - modify args or abort."""
    return HookResult(args=args)


async def post_call(result, args: dict, context: ToolCallContext) -> HookResult:
    """Post-call hook - modify result."""
    return HookResult(result=result)
''',
        "config": """mcp_servers:
  example:
    command: echo
    args: ["hello"]

tool_views:
  default:
    description: "Default view"
    exposure_mode: direct
""",
    }
    click.echo(examples[what])


@click.command()
@config_option()
@click.argument("server_name", required=False)
def instructions(config: str | None, server_name: str | None):
    """Show server instructions from upstream MCP servers.

    If SERVER_NAME is provided, show instructions for that server only.
    Otherwise, show instructions for all configured servers.
    """
    from mcp_proxy.proxy import MCPProxy

    cfg = load_config(str(get_config_path(config)))

    if server_name and server_name not in cfg.mcp_servers:
        click.echo(f"Error: server '{server_name}' not found", err=True)
        raise SystemExit(1)

    servers_to_check = [server_name] if server_name else list(cfg.mcp_servers.keys())

    async def fetch_instructions():
        """Fetch instructions from upstream servers."""
        results = {}
        proxy = MCPProxy(cfg)

        for name in servers_to_check:
            try:
                client = await proxy._create_client(name)
                async with client:
                    init_result = client.initialize_result
                    if init_result and init_result.instructions:
                        results[name] = init_result.instructions
                    else:
                        results[name] = None
            except Exception as e:
                results[name] = {"error": str(e)}

        return results

    results = run_async(fetch_instructions())

    for name, result in results.items():
        if len(servers_to_check) > 1:
            click.echo(f"=== {name} ===")

        if isinstance(result, dict) and "error" in result:
            click.echo(f"Error: {result['error']}", err=True)
        elif result is None:
            click.echo("(no instructions provided)")
        else:
            click.echo(result)

        if len(servers_to_check) > 1:
            click.echo()
