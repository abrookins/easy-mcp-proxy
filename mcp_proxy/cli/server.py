"""Server management CLI commands."""

from typing import Any

import click

from mcp_proxy.cli.utils import (
    config_option,
    get_config_path,
    load_config_raw,
    save_config_raw,
)


@click.group()
def server():
    """Manage upstream MCP servers."""
    pass


@server.command("add")
@click.argument("name")
@config_option()
@click.option(
    "--command", "cmd", default=None, help="Command to run (for stdio servers)"
)
@click.option(
    "--args", "args_str", default=None, help="Comma-separated command arguments"
)
@click.option("--cwd", default=None, help="Working directory for stdio servers")
@click.option("--url", default=None, help="URL for remote HTTP servers")
@click.option("--env", multiple=True, help="Environment variables as KEY=VALUE")
@click.option("--header", multiple=True, help="HTTP headers as KEY=VALUE")
def server_add(
    name: str,
    config: str | None,
    cmd: str | None,
    args_str: str | None,
    cwd: str | None,
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

    if cwd and not cmd:
        click.echo("Error: --cwd requires --command", err=True)
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
        if cwd:
            server_config["cwd"] = cwd

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
        views_str = ", ".join(referencing_views)
        click.echo(
            f"Error: Server '{name}' is referenced by views: {views_str}. "
            f"Use --force to remove anyway.",
            err=True,
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
    """Set custom description for a tool.

    Use {original} to include original description.
    """
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


@server.command("rename-tool")
@click.argument("server_name")
@click.argument("tool_name")
@click.argument("new_name")
@config_option()
def server_rename_tool(
    server_name: str, tool_name: str, new_name: str, config: str | None
):
    """Rename a tool (expose under a different name)."""
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

    # Set name
    server_config["tools"][tool_name]["name"] = new_name

    save_config_raw(config_path, data)
    click.echo(f"Renamed '{server_name}.{tool_name}' to '{new_name}'")


@server.command("set-tool-param")
@click.argument("server_name")
@click.argument("tool_name")
@click.argument("param_name")
@config_option()
@click.option("--hidden", is_flag=True, help="Hide this parameter from exposed schema")
@click.option("--default", "default_val", default=None, help="Default value to inject")
@click.option(
    "--rename", "rename_to", default=None, help="Expose parameter under different name"
)
@click.option("--description", default=None, help="Override parameter description")
@click.option("--clear", is_flag=True, help="Remove parameter configuration")
def server_set_tool_param(
    server_name: str,
    tool_name: str,
    param_name: str,
    config: str | None,
    hidden: bool,
    default_val: str | None,
    rename_to: str | None,
    description: str | None,
    clear: bool,
):
    """Configure parameter binding for a tool.

    Hide parameters, set defaults, rename, or override descriptions.

    Examples:

    \b
      # Hide 'path' and inject default
      mcp-proxy server set-tool-param myserver mytool path --hidden --default "."

    \b
      # Rename 'path' to 'folder'
      mcp-proxy server set-tool-param myserver mytool path --rename folder

    \b
      # Override description
      mcp-proxy server set-tool-param myserver mytool query --description "Search query"

    \b
      # Clear parameter config
      mcp-proxy server set-tool-param myserver mytool path --clear
    """
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

    tool_config = server_config["tools"][tool_name]

    # Ensure parameters dict exists
    if "parameters" not in tool_config:
        tool_config["parameters"] = {}

    if clear:
        # Remove parameter config
        if param_name in tool_config["parameters"]:
            del tool_config["parameters"][param_name]
            if not tool_config["parameters"]:
                del tool_config["parameters"]
        click.echo(f"Cleared parameter config for '{param_name}'")
    else:
        # Build parameter config
        param_config: dict[str, Any] = {}
        if hidden:
            param_config["hidden"] = True
        if default_val is not None:
            # Try to parse as JSON for complex values
            import json

            try:
                param_config["default"] = json.loads(default_val)
            except json.JSONDecodeError:
                param_config["default"] = default_val
        if rename_to:
            param_config["rename"] = rename_to
        if description:
            param_config["description"] = description

        if not param_config:
            click.echo(
                "Error: At least one of --hidden, --default, --rename, "
                "or --description required",
                err=True,
            )
            raise SystemExit(1)

        tool_config["parameters"][param_name] = param_config
        click.echo(f"Updated parameter '{param_name}' for '{server_name}.{tool_name}'")

    save_config_raw(config_path, data)
