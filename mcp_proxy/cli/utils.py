"""CLI utility functions and decorators."""

import asyncio
from pathlib import Path
from typing import Any

import click
import yaml

# Module-level config paths - these are mutable to allow monkeypatching in tests
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
    # Import to support monkeypatching from tests that patch mcp_proxy.cli
    import mcp_proxy.cli as cli_module

    if config:
        return Path(config)

    # Use the cli module's current values (allows monkeypatching)
    default_config_file = cli_module.DEFAULT_CONFIG_FILE
    default_config_dir = cli_module.DEFAULT_CONFIG_DIR

    # Use default location
    if not default_config_file.exists():
        default_config_dir.mkdir(parents=True, exist_ok=True)
        default_config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

    return default_config_file


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
        "--config",
        "-c",
        default=None,
        type=click.Path(exists=False),
        help=f"Config file path (default: {DEFAULT_CONFIG_FILE})",
    )
