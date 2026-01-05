"""Main CLI commands for mcp-proxy."""

import click

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
def tools(config: str | None, server: str | None):
    """List all tools from configured servers."""
    cfg = load_config(str(get_config_path(config)))

    # List tools configured directly on mcp_servers
    for server_name, server_config in cfg.mcp_servers.items():
        if server and server_name != server:
            continue
        if server_config.tools:
            for tool_name in server_config.tools:
                click.echo(f"{server_name}.{tool_name}")

    # List tools from tool_views
    for view_name, view_config in cfg.tool_views.items():
        if view_config.tools:
            for server_name, tools_dict in view_config.tools.items():
                if server and server_name != server:
                    continue
                for tool_name in tools_dict:
                    click.echo(f"{server_name}.{tool_name}")


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
            params = json_module.dumps(tool_schema.get("inputSchema", {}), indent=2)
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
def schema(
    tool_name: str | None, config: str | None, as_json: bool, server: str | None
):
    """Show schema for a specific tool or all tools."""
    import json as json_module

    from mcp_proxy.proxy import MCPProxy

    cfg = load_config(str(get_config_path(config)))
    proxy = MCPProxy(cfg)

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

        if server_name not in cfg.mcp_servers:
            click.echo(f"Error: server '{server_name}' not found", err=True)
            raise SystemExit(1)

        all_tools = run_async(fetch_schemas())
        server_tools = all_tools.get(server_name, [])

        if isinstance(server_tools, dict) and "error" in server_tools:
            _output_connection_error(
                server_name, server_tools["error"], as_json, is_tool=True
            )
            raise SystemExit(1)

        tool_schema = next((t for t in server_tools if t["name"] == tool), None)
        _output_tool_schema(tool_name, tool_schema, as_json)

    elif server:
        if server not in cfg.mcp_servers:
            click.echo(f"Error: server '{server}' not found", err=True)
            raise SystemExit(1)

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
    "--auth/--no-auth",
    default=False,
    help="Enable auth using MCP_PROXY_AUTH_CLIENT_ID and MCP_PROXY_AUTH_CLIENT_SECRET",
)
@click.option(
    "--oauth-client-id",
    envvar="MCP_PROXY_OAUTH_CLIENT_ID",
    help="OAuth client ID for HTTP auth (or set MCP_PROXY_OAUTH_CLIENT_ID)",
)
@click.option(
    "--oauth-client-secret",
    envvar="MCP_PROXY_OAUTH_CLIENT_SECRET",
    help="OAuth client secret for HTTP auth (or set MCP_PROXY_OAUTH_CLIENT_SECRET)",
)
@click.option(
    "--oauth-token-url",
    envvar="MCP_PROXY_OAUTH_TOKEN_URL",
    help="OAuth token URL for HTTP auth (or set MCP_PROXY_OAUTH_TOKEN_URL)",
)
@click.option(
    "--oauth-audience",
    envvar="MCP_PROXY_OAUTH_AUDIENCE",
    help="OAuth audience for HTTP auth (or set MCP_PROXY_OAUTH_AUDIENCE)",
)
@click.option(
    "--issuer-url",
    envvar="MCP_PROXY_ISSUER_URL",
    help="Public URL for OAuth discovery (or MCP_PROXY_ISSUER_URL). For --auth.",
)
def serve(
    config: str | None,
    transport: str,
    port: int,
    env_file: str,
    auth: bool,
    oauth_client_id: str | None,
    oauth_client_secret: str | None,
    oauth_token_url: str | None,
    oauth_audience: str | None,
    issuer_url: str | None,
):  # pragma: no cover
    """Start the MCP proxy server.

    For simple authentication (HTTP only), use --auth and set:
      MCP_PROXY_AUTH_CLIENT_ID     - Client ID
      MCP_PROXY_AUTH_CLIENT_SECRET - Client secret

    Clients authenticate with Bearer token (base64 client_id:client_secret)
    or HTTP Basic auth.
    """
    import os

    from dotenv import load_dotenv

    from mcp_proxy.models import OAuthConfig
    from mcp_proxy.proxy import MCPProxy

    # Load environment variables from .env file
    load_dotenv(env_file)

    cfg = load_config(str(get_config_path(config)))

    # Simple auth mode - use StaticTokenValidator
    if auth:
        if transport != "http":
            raise click.ClickException("--auth requires --transport http")

        client_id = os.environ.get("MCP_PROXY_AUTH_CLIENT_ID")
        client_secret = os.environ.get("MCP_PROXY_AUTH_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise click.ClickException(
                "--auth requires environment variables:\n"
                "  MCP_PROXY_AUTH_CLIENT_ID\n"
                "  MCP_PROXY_AUTH_CLIENT_SECRET"
            )

        # Get issuer_url from env if not passed via CLI (since dotenv loads after click)
        actual_issuer_url = issuer_url or os.environ.get("MCP_PROXY_ISSUER_URL")

        proxy = MCPProxy(cfg)
        proxy.run_with_static_auth(
            client_id=client_id,
            client_secret=client_secret,
            port=port,
            issuer_url=actual_issuer_url,
        )
        return

    # Override auth config from CLI options if provided (full OAuth flow)
    if oauth_client_id and oauth_client_secret and oauth_token_url:
        cfg.auth = OAuthConfig(
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            token_url=oauth_token_url,
            audience=oauth_audience,
        )

    proxy = MCPProxy(cfg)
    proxy.run(transport=transport, port=port)


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
