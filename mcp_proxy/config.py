"""Configuration loading for MCP Proxy."""

from pathlib import Path

import yaml

from mcp_proxy.models import ProxyConfig


def load_config(path: str | Path) -> ProxyConfig:
    """Load configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    return ProxyConfig(**data)

