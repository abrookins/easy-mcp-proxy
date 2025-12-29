"""Configuration loading for MCP Proxy."""

from pathlib import Path

import yaml

from mcp_proxy.models import ProxyConfig
from mcp_proxy.utils import substitute_env_vars


def load_config(path: str | Path) -> ProxyConfig:
    """Load configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

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
