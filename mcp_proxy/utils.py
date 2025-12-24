"""Utility functions for MCP Proxy."""

import os
import re
from typing import Any


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} environment variable references in a string.

    If the environment variable is not set, the placeholder is left unchanged.

    Args:
        value: String potentially containing ${VAR} references

    Returns:
        String with environment variables expanded
    """
    pattern = r"\$\{([^}]+)\}"
    return re.sub(pattern, lambda m: os.environ.get(m.group(1), m.group(0)), value)


def substitute_env_vars(obj: Any) -> Any:
    """Recursively substitute ${VAR} with environment variables in nested structures.

    Works on strings, dicts, and lists. Other types are returned unchanged.

    Args:
        obj: A string, dict, list, or any other value

    Returns:
        The input with all ${VAR} references in strings expanded
    """
    if isinstance(obj, str):
        return expand_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: substitute_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [substitute_env_vars(item) for item in obj]
    return obj

