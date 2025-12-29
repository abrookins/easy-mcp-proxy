"""View management CLI commands."""

from typing import Any

import click

from mcp_proxy.cli.utils import (
    config_option,
    get_config_path,
    load_config_raw,
    save_config_raw,
)


@click.group()
def view():
    """Manage tool views."""
    pass


@view.command("create")
@click.argument("name")
@config_option()
@click.option("--description", "-d", default=None, help="View description")
@click.option(
    "--exposure-mode",
    default="direct",
    type=click.Choice(["direct", "search"]),
    help="Tool exposure mode",
)
def view_create(
    name: str, config: str | None, description: str | None, exposure_mode: str
):
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
@click.option(
    "--tools",
    "tools_str",
    default=None,
    help="Comma-separated list of tools to include",
)
@click.option(
    "--all", "include_all", is_flag=True, help="Include all tools from server"
)
def view_add_server(
    view_name: str,
    server_name: str,
    config: str | None,
    tools_str: str | None,
    include_all: bool,
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
def view_set_tools(
    view_name: str, server_name: str, tools_str: str, config: str | None
):
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
    config: str | None,
):
    """Set custom description for a tool in a view.

    Use {original} to include original.
    """
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


@view.command("rename-tool")
@click.argument("view_name")
@click.argument("server_name")
@click.argument("tool_name")
@click.argument("new_name")
@config_option()
def view_rename_tool(
    view_name: str, server_name: str, tool_name: str, new_name: str, config: str | None
):
    """Rename a tool in a view (expose under a different name)."""
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

    # Set name
    view_config["tools"][server_name][tool_name]["name"] = new_name

    save_config_raw(config_path, data)
    click.echo(f"Renamed '{view_name}/{server_name}.{tool_name}' to '{new_name}'")


@view.command("set-tool-param")
@click.argument("view_name")
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
def view_set_tool_param(
    view_name: str,
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
    """Configure parameter binding for a tool in a view.

    Hide parameters, set defaults, rename, or override descriptions.

    Examples:

    \b
      # Hide 'path' and inject default
      mcp-proxy view set-tool-param myview myserver mytool path --hidden --default "."

    \b
      # Rename 'path' to 'folder'
      mcp-proxy view set-tool-param myview myserver mytool path --rename folder

    \b
      # Clear parameter config
      mcp-proxy view set-tool-param myview myserver mytool path --clear
    """
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

    tool_config = view_config["tools"][server_name][tool_name]

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
        click.echo(
            f"Updated parameter '{param_name}' for "
            f"'{view_name}/{server_name}.{tool_name}'"
        )

    save_config_raw(config_path, data)
