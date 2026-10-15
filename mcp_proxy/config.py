"""Configuration loading for MCP Proxy."""

import json
from pathlib import Path
from typing import Any

import yaml

from mcp_proxy.models import ProxyConfig
from mcp_proxy.utils import substitute_env_vars


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep merge overrides into base config."""
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_overrides_path(config_path: Path) -> Path:
    """Get the path for the overrides file (JSON next to YAML)."""
    return config_path.with_suffix(".overrides.json")


def load_overrides(config_path: Path) -> dict[str, Any]:
    """Load saved overrides from JSON file."""
    overrides_path = get_overrides_path(config_path)
    if not overrides_path.exists():
        return {}
    with open(overrides_path) as f:
        return json.load(f)


def load_config(path: str | Path, apply_overrides: bool = True) -> ProxyConfig:
    """Load configuration from a YAML file.

    Args:
        path: Path to the YAML config file
        apply_overrides: If True, also load and merge overrides from .overrides.json

    Returns:
        Validated ProxyConfig object
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

    # Apply overrides if enabled and overrides file exists
    if apply_overrides:
        overrides = load_overrides(path)
        if overrides:
            data = _deep_merge(data, overrides)

    data = substitute_env_vars(data)
    return ProxyConfig(**data)


def validate_config(config: ProxyConfig) -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []

    # Check tool view references to servers
    for view_name, view_config in config.tool_views.items():
        for server_name in view_config.tools.keys():
            if server_name not in config.mcp_servers:
                errors.append(
                    f"View '{view_name}' references unknown server '{server_name}'"
                )

        # Check hook paths
        if view_config.hooks:
            if view_config.hooks.pre_call:
                try:
                    from mcp_proxy.hooks import load_hook

                    load_hook(view_config.hooks.pre_call)
                except (ImportError, AttributeError) as e:
                    errors.append(f"View '{view_name}' has invalid pre_call hook: {e}")
            if view_config.hooks.post_call:
                try:
                    from mcp_proxy.hooks import load_hook

                    load_hook(view_config.hooks.post_call)
                except (ImportError, AttributeError) as e:
                    errors.append(f"View '{view_name}' has invalid post_call hook: {e}")

    return errors
