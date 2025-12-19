"""Configuration loading for MCP Proxy."""

import os
import re
from pathlib import Path

import yaml

from mcp_proxy.models import ProxyConfig


def _substitute_env_vars(obj):
    """Recursively substitute ${VAR} with environment variables."""
    if isinstance(obj, str):
        pattern = r"\$\{([^}]+)\}"
        return re.sub(pattern, lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    elif isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_env_vars(item) for item in obj]
    return obj


def load_config(path: str | Path) -> ProxyConfig:
    """Load configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    data = _substitute_env_vars(data)
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
                    errors.append(
                        f"View '{view_name}' has invalid pre_call hook: {e}"
                    )
            if view_config.hooks.post_call:
                try:
                    from mcp_proxy.hooks import load_hook
                    load_hook(view_config.hooks.post_call)
                except (ImportError, AttributeError) as e:
                    errors.append(
                        f"View '{view_name}' has invalid post_call hook: {e}"
                    )

    return errors

