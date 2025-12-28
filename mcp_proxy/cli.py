"""CLI commands for mcp-proxy."""

import asyncio
from pathlib import Path
from typing import Any

import click
import yaml

from mcp_proxy.config import load_config

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "mcp-proxy"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


def run_async(coro):
    """Run an async coroutine from sync CLI code."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def get_config_path(config: str | None) -> Path:
    """Get config file path, creating default if needed."""
    if config:
        return Path(config)

    # Use default location
    if not DEFAULT_CONFIG_FILE.exists():
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONFIG_FILE.write_text("mcp_servers: {}\ntool_views: {}\n")

    return DEFAULT_CONFIG_FILE


def load_config_raw(config_path: Path) -> dict[str, Any]:
    """Load config as raw dict to preserve structure for editing."""
    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        click.echo(f"Error: Invalid YAML in config file: {e}", err=True)
        raise SystemExit(1)

    # Ensure required keys exist
    if "mcp_servers" not in data:
        data["mcp_servers"] = {}
    if "tool_views" not in data:
        data["tool_views"] = {}
    return data


def save_config_raw(config_path: Path, data: dict[str, Any]) -> None:
    """Save config dict back to YAML file."""
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def config_option(required: bool = False):
    """Decorator for --config option."""
    return click.option(
        "--config", "-c",
        default=None,
        type=click.Path(exists=False),
        help=f"Config file path (default: {DEFAULT_CONFIG_FILE})"
    )


@click.group()
def main():
    """MCP Tool View Proxy CLI."""
    pass


@main.command()
@config_option()
def servers(config: str | None):
    """List configured upstream servers."""
    cfg = load_config(str(get_config_path(config)))
    for name in cfg.mcp_servers:
        click.echo(name)


@main.command()
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


@main.command()
@click.argument("tool_name", required=False)
@config_option()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--server", "-s", default=None, help="Filter by server name")
def schema(tool_name: str | None, config: str | None, as_json: bool, server: str | None):
    """Show schema for a specific tool or all tools."""
    import json as json_module

    from mcp_proxy.proxy import MCPProxy

    cfg = load_config(str(get_config_path(config)))
    proxy = MCPProxy(cfg)

    async def fetch_schemas():
        """Fetch schemas from upstream servers."""
        all_tools = {}

        for server_name, server_config in cfg.mcp_servers.items():
            try:
                client = await proxy._create_client(server_name)
                async with client:
                    tools = await client.list_tools()
                    # Filter tools based on config's tool constraints
                    allowed_tools = server_config.tools.keys() if server_config.tools else None
                    all_tools[server_name] = [
                        {"name": t.name, "description": getattr(t, "description", ""), "inputSchema": getattr(t, "inputSchema", {})}
                        for t in tools
                        if allowed_tools is None or t.name in allowed_tools
                    ]
            except Exception as e:
                all_tools[server_name] = {"error": str(e)}

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
            if as_json:
                click.echo(json_module.dumps({"tool": tool_name, "error": server_tools["error"]}))
            else:
                click.echo(f"Error connecting to {server_name}: {server_tools['error']}", err=True)
            raise SystemExit(1)

        tool_schema = next((t for t in server_tools if t["name"] == tool), None)

        if as_json:
            if tool_schema:
                click.echo(json_module.dumps({"tool": tool_name, "schema": tool_schema}))
            else:
                click.echo(json_module.dumps({"tool": tool_name, "error": "not found"}))
        else:
            if tool_schema:
                click.echo(f"Tool: {tool_name}")
                click.echo(f"Description: {tool_schema.get('description', 'N/A')}")
                click.echo(f"Parameters: {json_module.dumps(tool_schema.get('inputSchema', {}), indent=2)}")
            else:
                click.echo(f"Tool '{tool}' not found on server '{server_name}'")

    elif server:
        if server not in cfg.mcp_servers:
            click.echo(f"Error: server '{server}' not found", err=True)
            raise SystemExit(1)

        all_tools = run_async(fetch_schemas())
        server_tools = all_tools.get(server, [])

        if isinstance(server_tools, dict) and "error" in server_tools:
            if as_json:
                click.echo(json_module.dumps({"server": server, "error": server_tools["error"]}))
            else:
                click.echo(f"Error connecting to {server}: {server_tools['error']}", err=True)
            raise SystemExit(1)

        if as_json:
            click.echo(json_module.dumps({"server": server, "tools": server_tools}))
        else:
            click.echo(f"Server: {server}")
            click.echo(f"Tools ({len(server_tools)}):")
            for t in server_tools:
                click.echo(f"  - {t['name']}: {t.get('description', 'No description')}")
    else:
        # List all schemas
        all_tools = run_async(fetch_schemas())
        if as_json:
            click.echo(json_module.dumps({"tools": all_tools}))
        else:
            for server_name, tools in all_tools.items():
                if isinstance(tools, dict) and "error" in tools:
                    click.echo(f"{server_name}: error - {tools['error']}")
                else:
                    click.echo(f"{server_name}: {len(tools)} tools")
                    for t in tools:
                        click.echo(f"  - {t['name']}")


@main.command()
@config_option()
@click.option("--check-connections", "-C", is_flag=True, help="Check upstream server connections")
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
                            tools = await client.list_tools()
                            results[server_name] = {"status": "connected", "tools": len(tools)}
                    except Exception as e:
                        results[server_name] = {"status": "failed", "error": str(e)}
                return results

            results = run_async(check_all())
            all_ok = True
            for server_name, result in results.items():
                if result["status"] == "connected":
                    click.echo(f"  {server_name}: connected ({result['tools']} tools)")
                else:
                    click.echo(f"  {server_name}: connection failed - {result['error']}", err=True)
                    all_ok = False

            if not all_ok:
                raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@main.command()
@config_option()
@click.option("--transport", "-t", default="stdio", type=click.Choice(["stdio", "http"]), help="Transport type")
@click.option("--port", "-p", default=8000, type=int, help="Port for HTTP transport")
@click.option("--env-file", "-e", default=".env", type=click.Path(), help="Path to .env file (default: .env)")
def serve(config: str | None, transport: str, port: int, env_file: str):  # pragma: no cover
    """Start the MCP proxy server."""
    from dotenv import load_dotenv

    from mcp_proxy.proxy import MCPProxy

    # Load environment variables from .env file
    load_dotenv(env_file)

    cfg = load_config(str(get_config_path(config)))
    proxy = MCPProxy(cfg)
    proxy.run(transport=transport, port=port)


@main.command()
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


@main.command("config")
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


@main.command()
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
        "config": '''mcp_servers:
  example:
    command: echo
    args: ["hello"]

tool_views:
  default:
    description: "Default view"
    exposure_mode: direct
''',
    }
    click.echo(examples[what])


# =============================================================================
# Server command group
# =============================================================================


@main.group()
def server():
    """Manage upstream MCP servers."""
    pass


@server.command("add")
@click.argument("name")
@config_option()
@click.option("--command", "cmd", default=None, help="Command to run (for stdio servers)")
@click.option("--args", "args_str", default=None, help="Comma-separated command arguments")
@click.option("--url", default=None, help="URL for remote HTTP servers")
@click.option("--env", multiple=True, help="Environment variables as KEY=VALUE")
@click.option("--header", multiple=True, help="HTTP headers as KEY=VALUE")
def server_add(
    name: str,
    config: str | None,
    cmd: str | None,
    args_str: str | None,
    url: str | None,
    env: tuple[str, ...],
    header: tuple[str, ...],
):
    """Add a new upstream server."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    # Validation
    if name in data["mcp_servers"]:
        click.echo(f"Error: Server '{name}' already exists", err=True)
        raise SystemExit(1)

    if not cmd and not url:
        click.echo("Error: Either --command or --url must be provided", err=True)
        raise SystemExit(1)

    if cmd and url:
        click.echo("Error: Cannot specify both --command and --url", err=True)
        raise SystemExit(1)

    if args_str and not cmd:
        click.echo("Error: --args requires --command", err=True)
        raise SystemExit(1)

    if header and not url:
        click.echo("Error: --header requires --url", err=True)
        raise SystemExit(1)

    # Build server config
    server_config: dict[str, Any] = {}

    if cmd:
        server_config["command"] = cmd
        if args_str:
            server_config["args"] = args_str.split(",")

    if url:
        server_config["url"] = url

    # Parse env vars
    if env:
        env_dict = {}
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                env_dict[k] = v
        if env_dict:
            server_config["env"] = env_dict

    # Parse headers
    if header:
        headers_dict = {}
        for h in header:
            if "=" in h:
                k, v = h.split("=", 1)
                headers_dict[k] = v
        if headers_dict:
            server_config["headers"] = headers_dict

    # Add to config
    data["mcp_servers"][name] = server_config
    save_config_raw(config_path, data)
    click.echo(f"Added server '{name}'")




@server.command("remove")
@click.argument("name")
@config_option()
@click.option("--force", is_flag=True, help="Force removal even if referenced by views")
def server_remove(name: str, config: str | None, force: bool):
    """Remove an upstream server."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if name not in data["mcp_servers"]:
        click.echo(f"Error: Server '{name}' not found", err=True)
        raise SystemExit(1)

    # Check if server is referenced by any views
    referencing_views = []
    for view_name, view_config in data.get("tool_views", {}).items():
        if isinstance(view_config, dict) and name in view_config.get("tools", {}):
            referencing_views.append(view_name)

    if referencing_views and not force:
        click.echo(
            f"Error: Server '{name}' is referenced by views: {', '.join(referencing_views)}. "
            f"Use --force to remove anyway.",
            err=True
        )
        raise SystemExit(1)

    # Remove server
    del data["mcp_servers"][name]

    # If force, also clean up view references
    if force and referencing_views:
        for view_name in referencing_views:
            # referencing_views only contains views that have this server in tools
            del data["tool_views"][view_name]["tools"][name]

    save_config_raw(config_path, data)
    click.echo(f"Removed server '{name}'")


@server.command("list")
@config_option()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show server details")
def server_list(config: str | None, as_json: bool, verbose: bool):
    """List all configured servers."""
    import json as json_module

    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    servers = data.get("mcp_servers", {})

    if as_json:
        click.echo(json_module.dumps(servers, indent=2))
    elif verbose:
        for name, server_config in servers.items():
            click.echo(f"{name}:")
            if server_config.get("command"):
                click.echo(f"  command: {server_config['command']}")
                if server_config.get("args"):
                    click.echo(f"  args: {server_config['args']}")
            if server_config.get("url"):
                click.echo(f"  url: {server_config['url']}")
            if server_config.get("env"):
                click.echo(f"  env: {list(server_config['env'].keys())}")
            if server_config.get("tools"):
                click.echo(f"  tools: {list(server_config['tools'].keys())}")
    else:
        for name in servers:
            click.echo(name)


@server.command("set-tools")
@click.argument("name")
@click.argument("tools_str")
@config_option()
def server_set_tools(name: str, tools_str: str, config: str | None):
    """Set tool allowlist for a server (comma-separated)."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if name not in data["mcp_servers"]:
        click.echo(f"Error: Server '{name}' not found", err=True)
        raise SystemExit(1)

    # Parse tools list
    if tools_str.strip():
        tools = [t.strip() for t in tools_str.split(",") if t.strip()]
        data["mcp_servers"][name]["tools"] = {t: {} for t in tools}
    else:
        # Empty string clears tools
        if "tools" in data["mcp_servers"][name]:
            del data["mcp_servers"][name]["tools"]

    save_config_raw(config_path, data)
    click.echo(f"Updated tools for server '{name}'")


@server.command("clear-tools")
@click.argument("name")
@config_option()
def server_clear_tools(name: str, config: str | None):
    """Clear tool filtering for a server (expose all tools)."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if name not in data["mcp_servers"]:
        click.echo(f"Error: Server '{name}' not found", err=True)
        raise SystemExit(1)

    if "tools" in data["mcp_servers"][name]:
        del data["mcp_servers"][name]["tools"]

    save_config_raw(config_path, data)
    click.echo(f"Cleared tool filter for server '{name}'")


@server.command("set-tool-description")
@click.argument("server_name")
@click.argument("tool_name")
@click.argument("description")
@config_option()
def server_set_tool_description(
    server_name: str, tool_name: str, description: str, config: str | None
):
    """Set custom description for a tool. Use {original} to include original description."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if server_name not in data["mcp_servers"]:
        click.echo(f"Error: Server '{server_name}' not found", err=True)
        raise SystemExit(1)

    server_config = data["mcp_servers"][server_name]

    # Ensure tools dict exists
    if "tools" not in server_config:
        server_config["tools"] = {}

    # Ensure tool entry exists
    if tool_name not in server_config["tools"]:
        server_config["tools"][tool_name] = {}

    # Set or clear description
    if description:
        server_config["tools"][tool_name]["description"] = description
    else:
        # Empty description clears it
        if "description" in server_config["tools"][tool_name]:
            del server_config["tools"][tool_name]["description"]

    save_config_raw(config_path, data)
    click.echo(f"Updated description for '{server_name}.{tool_name}'")



# =============================================================================
# View command group
# =============================================================================


@main.group()
def view():
    """Manage tool views."""
    pass


@view.command("create")
@click.argument("name")
@config_option()
@click.option("--description", "-d", default=None, help="View description")
@click.option("--exposure-mode", default="direct", type=click.Choice(["direct", "search"]),
              help="Tool exposure mode")
def view_create(name: str, config: str | None, description: str | None, exposure_mode: str):
    """Create a new tool view."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if name in data["tool_views"]:
        click.echo(f"Error: View '{name}' already exists", err=True)
        raise SystemExit(1)

    view_config: dict[str, Any] = {}
    if description:
        view_config["description"] = description
    if exposure_mode != "direct":
        view_config["exposure_mode"] = exposure_mode

    data["tool_views"][name] = view_config
    save_config_raw(config_path, data)
    click.echo(f"Created view '{name}'")


@view.command("delete")
@click.argument("name")
@config_option()
def view_delete(name: str, config: str | None):
    """Delete a tool view."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if name not in data["tool_views"]:
        click.echo(f"Error: View '{name}' not found", err=True)
        raise SystemExit(1)

    del data["tool_views"][name]
    save_config_raw(config_path, data)
    click.echo(f"Deleted view '{name}'")


@view.command("list")
@config_option()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show view details")
def view_list(config: str | None, as_json: bool, verbose: bool):
    """List all configured views."""
    import json as json_module

    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    views = data.get("tool_views", {})

    if as_json:
        click.echo(json_module.dumps(views, indent=2))
    elif verbose:
        for name, view_config in views.items():
            click.echo(f"{name}:")
            if view_config.get("description"):
                click.echo(f"  description: {view_config['description']}")
            if view_config.get("exposure_mode"):
                click.echo(f"  exposure_mode: {view_config['exposure_mode']}")
            if view_config.get("tools"):
                click.echo("  tools:")
                for server_name, tools in view_config["tools"].items():
                    click.echo(f"    {server_name}: {list(tools.keys())}")
    else:
        for name in views:
            click.echo(name)


@view.command("add-server")
@click.argument("view_name")
@click.argument("server_name")
@config_option()
@click.option("--tools", "tools_str", default=None, help="Comma-separated list of tools to include")
@click.option("--all", "include_all", is_flag=True, help="Include all tools from server")
def view_add_server(
    view_name: str,
    server_name: str,
    config: str | None,
    tools_str: str | None,
    include_all: bool
):
    """Add a server to a view."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if view_name not in data["tool_views"]:
        click.echo(f"Error: View '{view_name}' not found", err=True)
        raise SystemExit(1)

    if server_name not in data["mcp_servers"]:
        click.echo(f"Error: Server '{server_name}' not found", err=True)
        raise SystemExit(1)

    view_config = data["tool_views"][view_name]

    # Ensure tools dict exists
    if "tools" not in view_config:
        view_config["tools"] = {}

    # Build tools config for this server
    if include_all:
        # Empty dict means all tools
        view_config["tools"][server_name] = {}
    elif tools_str:
        tools = [t.strip() for t in tools_str.split(",") if t.strip()]
        view_config["tools"][server_name] = {t: {} for t in tools}
    else:
        # Default to empty (all tools)
        view_config["tools"][server_name] = {}

    save_config_raw(config_path, data)
    click.echo(f"Added server '{server_name}' to view '{view_name}'")


@view.command("remove-server")
@click.argument("view_name")
@click.argument("server_name")
@config_option()
def view_remove_server(view_name: str, server_name: str, config: str | None):
    """Remove a server from a view."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if view_name not in data["tool_views"]:
        click.echo(f"Error: View '{view_name}' not found", err=True)
        raise SystemExit(1)

    view_config = data["tool_views"][view_name]

    if "tools" not in view_config or server_name not in view_config.get("tools", {}):
        click.echo(f"Error: Server '{server_name}' not in view '{view_name}'", err=True)
        raise SystemExit(1)

    del view_config["tools"][server_name]
    save_config_raw(config_path, data)
    click.echo(f"Removed server '{server_name}' from view '{view_name}'")


@view.command("set-tools")
@click.argument("view_name")
@click.argument("server_name")
@click.argument("tools_str")
@config_option()
def view_set_tools(view_name: str, server_name: str, tools_str: str, config: str | None):
    """Set tool allowlist for a server in a view (comma-separated)."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if view_name not in data["tool_views"]:
        click.echo(f"Error: View '{view_name}' not found", err=True)
        raise SystemExit(1)

    view_config = data["tool_views"][view_name]

    # Ensure tools dict exists
    if "tools" not in view_config:
        view_config["tools"] = {}

    # Parse tools list and set
    if tools_str.strip():
        tools = [t.strip() for t in tools_str.split(",") if t.strip()]
        view_config["tools"][server_name] = {t: {} for t in tools}
    else:
        # Empty string clears tools for this server
        view_config["tools"][server_name] = {}

    save_config_raw(config_path, data)
    click.echo(f"Updated tools for '{server_name}' in view '{view_name}'")


@view.command("clear-tools")
@click.argument("view_name")
@click.argument("server_name")
@config_option()
def view_clear_tools(view_name: str, server_name: str, config: str | None):
    """Clear tool filtering for a server in a view (expose all tools from server)."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if view_name not in data["tool_views"]:
        click.echo(f"Error: View '{view_name}' not found", err=True)
        raise SystemExit(1)

    view_config = data["tool_views"][view_name]

    if "tools" not in view_config or server_name not in view_config.get("tools", {}):
        click.echo(f"Error: Server '{server_name}' not in view '{view_name}'", err=True)
        raise SystemExit(1)

    # Clear to empty dict (means all tools)
    view_config["tools"][server_name] = {}

    save_config_raw(config_path, data)
    click.echo(f"Cleared tool filter for '{server_name}' in view '{view_name}'")



@view.command("set-tool-description")
@click.argument("view_name")
@click.argument("server_name")
@click.argument("tool_name")
@click.argument("description")
@config_option()
def view_set_tool_description(
    view_name: str,
    server_name: str,
    tool_name: str,
    description: str,
    config: str | None
):
    """Set custom description for a tool in a view. Use {original} to include original."""
    config_path = get_config_path(config)
    data = load_config_raw(config_path)

    if view_name not in data["tool_views"]:
        click.echo(f"Error: View '{view_name}' not found", err=True)
        raise SystemExit(1)

    view_config = data["tool_views"][view_name]

    # Ensure tools dict exists
    if "tools" not in view_config:
        view_config["tools"] = {}

    # Ensure server entry exists
    if server_name not in view_config["tools"]:
        view_config["tools"][server_name] = {}

    # Ensure tool entry exists
    if tool_name not in view_config["tools"][server_name]:
        view_config["tools"][server_name][tool_name] = {}

    # Set description
    if description:
        view_config["tools"][server_name][tool_name]["description"] = description
    else:
        if "description" in view_config["tools"][server_name][tool_name]:
            del view_config["tools"][server_name][tool_name]["description"]

    save_config_raw(config_path, data)
    click.echo(f"Updated description for '{view_name}/{server_name}.{tool_name}'")