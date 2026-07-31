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
    from mcp_proxy.models import OutputCacheConfig

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
    if config.output_cache and not config.output_cache.enabled:
        return None

    return OutputCacheConfig(enabled=True)


def is_cache_enabled(config: "ProxyConfig") -> bool:
    """Check if output caching is enabled at any level.

    Args:
        config: The proxy configuration

    Returns:
        True if caching is enabled at any level
    """
    if config.output_cache:
        if config.output_cache.enabled:
            return True
        for server_config in config.mcp_servers.values():
            if server_config.cache_outputs and server_config.cache_outputs.enabled:
                return True
            if server_config.tools:
                for tool_config in server_config.tools.values():
                    if tool_config.cache_output and tool_config.cache_output.enabled:
                        return True
        return False

    for server_config in config.mcp_servers.values():
        if server_config.cache_outputs is None:
            return True
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


def register_cache_retrieval_tool(
    mcp: FastMCP, secret: str, config: "OutputCacheConfig | None" = None
) -> None:
    """Register the retrieve_cached_output tool on an MCP instance.

    Args:
        mcp: FastMCP instance to register the tool on
        secret: The cache signing secret
        config: Output handling config for bounded retrieval
    """
    from mcp_proxy.cache import build_cached_output_payload, retrieve_by_token
    from mcp_proxy.models import OutputCacheConfig

    cache_config = config or OutputCacheConfig()

    def cached_output_payload(
        token: str,
        line_offset: int = 0,
        line_count: int | None = None,
        jmespath_expression: str | None = None,
        char_offset: int | None = None,
        char_count: int | None = None,
        allow_full: bool = False,
    ) -> dict:
        content = retrieve_by_token(token, secret)
        if content is None:
            return {"error": "Token not found, expired, or invalid"}
        return build_cached_output_payload(
            content,
            line_offset=line_offset,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
            char_offset=char_offset,
            char_count=char_count,
            allow_full=allow_full,
            config=cache_config,
        )

    def retrieve_cached_output(
        token: str,
        line_offset: int = 0,
        line_count: int | None = None,
        jmespath_expression: str | None = None,
        char_offset: int | None = None,
        char_count: int | None = None,
    ) -> dict:
        """Retrieve cached tool output as a bounded preview, range, or JSON query.

        When a tool's output is cached, you receive a preview and a token.
        This tool returns bounded content by default. Use line_offset and
        line_count, char_offset and char_count, or jmespath_expression to
        navigate larger cached output explicitly.

        Args:
            token: The cache token from a previous tool response
            line_offset: Zero-based number of lines to skip before returning content
            line_count: Maximum number of lines to return
            jmespath_expression: Optional JMESPath expression for JSON cached output
            char_offset: Optional zero-based character offset for range retrieval
            char_count: Optional maximum characters for range retrieval

        Returns:
            Cached output content and window metadata, or an error
        """
        return cached_output_payload(
            token,
            line_offset=line_offset,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
            char_offset=char_offset,
            char_count=char_count,
        )

    def preview_cached_output(
        token: str,
        line_offset: int = 0,
        line_count: int | None = None,
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

    def range_cached_output(
        token: str,
        char_offset: int = 0,
        char_count: int | None = None,
    ) -> dict:
        """Read a bounded character window from cached tool output.

        Args:
            token: The cache token from a previous tool response
            char_offset: Zero-based number of characters to skip
            char_count: Maximum characters to return

        Returns:
            Cached output character window and navigation metadata, or an error
        """
        return cached_output_payload(
            token,
            char_offset=char_offset,
            char_count=char_count,
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
            "Retrieve bounded cached tool output. "
            "When a tool's output is cached, you receive a preview and a token. "
            "Use line_offset and line_count for a configurable text window, "
            "char_offset and char_count for character ranges, or "
            "jmespath_expression to extract part of a JSON cached output. "
            "Omitting range/query parameters returns a bounded preview."
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
        name="range_cached_output",
        description=(
            "Read a bounded character window from cached tool output. "
            f"Requests are capped at {cache_config.retrieval_max_chars} chars."
        ),
    )(range_cached_output)
    mcp.tool(
        name="query_cached_output",
        description=(
            "Run a JMESPath expression against JSON cached tool output. "
            "Use optional line_offset and line_count to window the serialized "
            "query result when it is still large."
        ),
    )(query_cached_output)


def register_cache_resource(
    mcp: FastMCP, secret: str, config: "OutputCacheConfig | None" = None
) -> None:
    """Register the cached-output MCP resource template on an MCP instance.

    Args:
        mcp: FastMCP instance to register the resource on
        secret: The cache signing secret
        config: Output handling config for bounded retrieval
    """
    import json

    from mcp_proxy.cache import (
        CACHE_RESOURCE_URI_TEMPLATE,
        build_cached_output_payload,
        retrieve_by_token,
    )
    from mcp_proxy.models import OutputCacheConfig

    cache_config = config or OutputCacheConfig()

    @mcp.resource(
        CACHE_RESOURCE_URI_TEMPLATE,
        name="cached-output",
        description="Read bounded metadata and preview for cached tool output.",
    )
    def cached_output_resource(token: str) -> str:
        content = retrieve_by_token(token, secret)
        if content is None:
            raise ValueError("Token not found, expired, or invalid")
        return json.dumps(
            build_cached_output_payload(content, config=cache_config),
            default=str,
        )
