"""Output caching utilities for MCP Proxy.

This module provides functions for managing output caching configuration
and registering cache-related tools.
"""

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from mcp_proxy.models import OutputCacheConfig, ProxyConfig


def get_cache_config(
    config: "ProxyConfig", tool_name: str, server_name: str
) -> "OutputCacheConfig | None":
    """Get the effective cache configuration for a tool.

    Priority: tool config > server config > global config

    Args:
        config: The proxy configuration
        tool_name: Name of the tool
        server_name: Name of the upstream server

    Returns:
        OutputCacheConfig if caching is enabled, None otherwise
    """
    # Check tool-level config first
    server_config = config.mcp_servers.get(server_name)
    if server_config and server_config.tools:
        tool_config = server_config.tools.get(tool_name)
        if tool_config and tool_config.cache_output:
            if tool_config.cache_output.enabled:
                return tool_config.cache_output
            return None  # Explicitly disabled at tool level

    # Check server-level config
    if server_config and server_config.cache_outputs:
        if server_config.cache_outputs.enabled:
            return server_config.cache_outputs
        return None  # Explicitly disabled at server level

    # Check global config
    if config.output_cache and config.output_cache.enabled:
        return config.output_cache

    return None


def is_cache_enabled(config: "ProxyConfig") -> bool:
    """Check if output caching is enabled at any level.

    Args:
        config: The proxy configuration

    Returns:
        True if caching is enabled at any level
    """
    if config.output_cache and config.output_cache.enabled:
        return True
    for server_config in config.mcp_servers.values():
        if server_config.cache_outputs and server_config.cache_outputs.enabled:
            return True
        if server_config.tools:
            for tool_config in server_config.tools.values():
                if tool_config.cache_output and tool_config.cache_output.enabled:
                    return True
    return False


def get_cache_base_url(config: "ProxyConfig") -> str:
    """Get the base URL for cache retrieval.

    Args:
        config: The proxy configuration

    Returns:
        The configured base URL or default localhost
    """
    return config.cache_base_url or "http://localhost:8000"


def get_cache_secret(config: "ProxyConfig") -> str:
    """Get the cache signing secret, generating one if not configured.

    Args:
        config: The proxy configuration

    Returns:
        The cache secret string
    """
    if config.cache_secret:
        return config.cache_secret
    # Generate a random secret if not configured (warn in production)
    import secrets

    return secrets.token_hex(32)


def register_cache_retrieval_tool(mcp: FastMCP, secret: str) -> None:
    """Register the retrieve_cached_output tool on an MCP instance.

    Args:
        mcp: FastMCP instance to register the tool on
        secret: The cache signing secret
    """
    from mcp_proxy.cache import retrieve_by_token

    def retrieve_cached_output(token: str) -> dict:
        """Retrieve the full content of a cached tool output.

        When a tool's output is cached, you receive a preview and a token.
        Use this tool to retrieve the full content when you need it.

        Args:
            token: The cache token from a previous tool response

        Returns:
            The full cached output content, or an error if not found/expired
        """
        content = retrieve_by_token(token, secret)
        if content is None:
            return {"error": "Token not found, expired, or invalid"}
        return {"content": content}

    mcp.tool(
        name="retrieve_cached_output",
        description=(
            "Retrieve the full content of a cached tool output. "
            "When a tool's output is cached, you receive a preview and a token. "
            "Use this tool to retrieve the full content when you need it."
        ),
    )(retrieve_cached_output)
