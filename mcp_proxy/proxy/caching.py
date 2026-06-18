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
    from mcp_proxy.cache import build_cached_output_payload, retrieve_by_token

    def cached_output_payload(
        token: str,
        line_offset: int = 0,
        line_count: int | None = None,
        jmespath_expression: str | None = None,
    ) -> dict:
        content = retrieve_by_token(token, secret)
        if content is None:
            return {"error": "Token not found, expired, or invalid"}
        return build_cached_output_payload(
            content,
            line_offset=line_offset,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
        )

    def retrieve_cached_output(
        token: str,
        line_offset: int = 0,
        line_count: int | None = None,
        jmespath_expression: str | None = None,
    ) -> dict:
        """Retrieve cached tool output, optionally as a line window or JSON query.

        When a tool's output is cached, you receive a preview and a token.
        Use this tool to retrieve the full content, a zero-based line window,
        or the result of a JMESPath expression for JSON cached output.

        Args:
            token: The cache token from a previous tool response
            line_offset: Zero-based number of lines to skip before returning content
            line_count: Maximum number of lines to return; omit for all remaining lines
            jmespath_expression: Optional JMESPath expression for JSON cached output

        Returns:
            Cached output content and window metadata, or an error
        """
        return cached_output_payload(
            token,
            line_offset=line_offset,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
        )

    def preview_cached_output(
        token: str,
        line_offset: int = 0,
        line_count: int = 100,
    ) -> dict:
        """Preview a cached tool output using a configurable line window.

        Args:
            token: The cache token from a previous tool response
            line_offset: Zero-based number of lines to skip before returning content
            line_count: Maximum number of lines to return

        Returns:
            Cached output line window and navigation metadata, or an error
        """
        return cached_output_payload(
            token,
            line_offset=line_offset,
            line_count=line_count,
        )

    def query_cached_output(
        token: str,
        jmespath_expression: str,
        line_offset: int = 0,
        line_count: int | None = None,
    ) -> dict:
        """Query JSON cached output with JMESPath.

        Args:
            token: The cache token from a previous tool response
            jmespath_expression: JMESPath expression to run against JSON content
            line_offset: Zero-based number of serialized result lines to skip
            line_count: Maximum number of serialized result lines to return

        Returns:
            Serialized JMESPath result and optional line metadata, or an error
        """
        return cached_output_payload(
            token,
            line_offset=line_offset,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
        )

    mcp.tool(
        name="retrieve_cached_output",
        description=(
            "Retrieve cached tool output. "
            "When a tool's output is cached, you receive a preview and a token. "
            "Use line_offset and line_count for a configurable text window, "
            "or jmespath_expression to extract part of a JSON cached output. "
            "Omitting those parameters returns the full cached content."
        ),
    )(retrieve_cached_output)
    mcp.tool(
        name="preview_cached_output",
        description=(
            "Preview cached tool output using a configurable text window. "
            "Use line_offset and line_count to navigate large cached output "
            "without loading the full content."
        ),
    )(preview_cached_output)
    mcp.tool(
        name="query_cached_output",
        description=(
            "Run a JMESPath expression against JSON cached tool output. "
            "Use optional line_offset and line_count to window the serialized "
            "query result when it is still large."
        ),
    )(query_cached_output)


def register_cache_resource(mcp: FastMCP, secret: str) -> None:
    """Register the cached-output MCP resource template on an MCP instance.

    Args:
        mcp: FastMCP instance to register the resource on
        secret: The cache signing secret
    """
    from mcp_proxy.cache import CACHE_RESOURCE_URI_TEMPLATE, retrieve_by_token

    @mcp.resource(
        CACHE_RESOURCE_URI_TEMPLATE,
        name="cached-output",
        description="Read the full content of a cached tool output by token.",
    )
    def cached_output_resource(token: str) -> str:
        content = retrieve_by_token(token, secret)
        if content is None:
            raise ValueError("Token not found, expired, or invalid")
        return content
