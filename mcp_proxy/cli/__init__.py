"""CLI package for mcp-proxy."""

import click

from mcp_proxy.cli.commands import (
    call,
    config_cmd,
    init,
    schema,
    serve,
    servers,
    tools,
    validate,
)
from mcp_proxy.cli.server import server
from mcp_proxy.cli.utils import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    config_option,
    get_config_path,
    load_config_raw,
    run_async,
    save_config_raw,
)
from mcp_proxy.cli.view import view


@click.group()
def main():
    """MCP Tool View Proxy CLI."""
    pass


# Register top-level commands
main.add_command(servers)
main.add_command(tools)
main.add_command(schema)
main.add_command(validate)
main.add_command(serve)
main.add_command(call)
main.add_command(config_cmd)
main.add_command(init)

# Register command groups
main.add_command(server)
main.add_command(view)

__all__ = [
    "main",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_FILE",
    "config_option",
    "get_config_path",
    "load_config_raw",
    "run_async",
    "save_config_raw",
]

