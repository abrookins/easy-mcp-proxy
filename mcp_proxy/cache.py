"""Output caching for MCP Proxy.

This module provides functionality to cache large tool outputs to disk and
serve them via HTTP with expiring, signed URLs.

The caching flow:
1. Tool output is written to /tmp/mcp-proxy-cache/{token}.txt
2. An HMAC-signed URL is generated with expiration timestamp
3. LLM receives preview + URL instead of full output
4. LLM-written code fetches full output via HTTP or retrieve_cached_output tool
"""

import hashlib
import hmac
import json
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jmespath
from fastmcp.tools.tool import ToolResult
from mcp import types
from pydantic import BaseModel

# Cache directory in system temp
CACHE_DIR = Path(tempfile.gettempdir()) / "mcp-proxy-cache"
CACHE_RESOURCE_URI_TEMPLATE = "mcp://easy-mcp-proxy/cache/{token}"


class CachedOutputResponse(BaseModel):
    """Response returned when tool output is cached."""

    cached: bool = True
    token: str
    retrieve_url: str
    expires_at: str  # ISO 8601 timestamp
    preview: str
    size_bytes: int


def build_cache_resource_uri(token: str) -> str:
    """Build the MCP resource URI for a cached output token."""
    return CACHE_RESOURCE_URI_TEMPLATE.format(token=token)


def infer_cached_content_mime_type(content: str) -> str:
    """Infer a reasonable MIME type for cached content."""
    try:
        json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return "text/plain"
    return "application/json"


def build_cached_output_tool_result(
    cached_response: CachedOutputResponse,
    mime_type: str,
) -> ToolResult:
    """Build a tool result with MCP and signed-HTTP resource links."""
    preview_text = (
        f"{cached_response.preview}\n\n"
        "Output is cached. Use preview_cached_output for line windows, "
        "query_cached_output for JSON/JMESPath slices, or the cached resource "
        "links for full output."
    )
    resource_uri = build_cache_resource_uri(cached_response.token)
    structured_content = cached_response.model_dump()

    return ToolResult(
        content=[
            types.TextContent(type="text", text=preview_text),
            types.ResourceLink(
                type="resource_link",
                name="cached-output-mcp",
                title="Cached output via MCP",
                uri=resource_uri,
                description="Read the full cached output via resources/read.",
                mimeType=mime_type,
                size=cached_response.size_bytes,
            ),
            types.ResourceLink(
                type="resource_link",
                name="cached-output-http",
                title="Cached output via HTTPS",
                uri=cached_response.retrieve_url,
                description="Retrieve the full cached output using this signed URL.",
                mimeType=mime_type,
                size=cached_response.size_bytes,
                _meta={
                    "access": "signed_http",
                    "expires_at": cached_response.expires_at,
                },
            ),
        ],
        structured_content=structured_content,
    )


def ensure_cache_dir() -> Path:
    """Ensure the cache directory exists and return its path."""
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR


def generate_token() -> str:
    """Generate a unique token for a cached output."""
    return uuid.uuid4().hex


def sign_url(token: str, expires_at: int, secret: str) -> str:
    """Create HMAC signature for a cache URL.

    Args:
        token: The cache token
        expires_at: Unix timestamp when URL expires
        secret: HMAC signing secret

    Returns:
        Hex-encoded HMAC-SHA256 signature
    """
    message = f"{token}:{expires_at}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(token: str, expires_at: int, signature: str, secret: str) -> bool:
    """Verify an HMAC signature for a cache URL.

    Args:
        token: The cache token
        expires_at: Unix timestamp when URL expires
        signature: The signature to verify
        secret: HMAC signing secret

    Returns:
        True if signature is valid, False otherwise
    """
    expected_sig = sign_url(token, expires_at, secret)
    return hmac.compare_digest(signature, expected_sig)


def serialize_result(result: Any) -> str:
    """Serialize a tool result to a string for caching.

    Args:
        result: The tool result (can be dict, list, string, etc.)

    Returns:
        String representation of the result
    """
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, indent=2, default=str)
    except (TypeError, ValueError):
        return str(result)


def build_line_window_payload(
    content: str,
    line_offset: int = 0,
    line_count: int | None = None,
) -> dict[str, Any]:
    """Build a payload containing a configurable line window."""
    if line_offset < 0:
        raise ValueError("line_offset must be >= 0")
    if line_count is not None and line_count < 0:
        raise ValueError("line_count must be >= 0")

    lines = content.splitlines()
    total_lines = len(lines)
    if line_count is None:
        selected_lines = lines[line_offset:]
    else:
        selected_lines = lines[line_offset : line_offset + line_count]

    next_line_offset = line_offset + len(selected_lines)
    has_more = next_line_offset < total_lines

    return {
        "content": "\n".join(selected_lines),
        "line_offset": line_offset,
        "line_count": line_count,
        "returned_lines": len(selected_lines),
        "total_lines": total_lines,
        "next_line_offset": next_line_offset if has_more else None,
        "truncated": has_more,
    }


def build_cached_output_payload(
    content: str,
    line_offset: int = 0,
    line_count: int | None = None,
    jmespath_expression: str | None = None,
) -> dict[str, Any]:
    """Build a retrieval payload with optional JSON query and line window."""
    payload: dict[str, Any] = {}
    output = content

    if jmespath_expression is not None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {"error": "Cached output is not valid JSON"}

        try:
            query_result = jmespath.search(jmespath_expression, parsed)
        except jmespath.exceptions.JMESPathError as exc:
            return {"error": f"Invalid JMESPath expression: {exc}"}

        output = serialize_result(query_result)
        payload["jmespath_expression"] = jmespath_expression

    if line_offset != 0 or line_count is not None:
        try:
            window_payload = build_line_window_payload(output, line_offset, line_count)
        except ValueError as exc:
            return {"error": str(exc)}
        return {**payload, **window_payload}

    payload["content"] = output
    return payload


def create_cached_output(
    content: str,
    secret: str,
    base_url: str,
    ttl_seconds: int,
    preview_chars: int,
) -> CachedOutputResponse:
    """Cache tool output and return metadata with retrieval URL.

    Args:
        content: The content to cache
        secret: HMAC signing secret
        base_url: Base URL for cache retrieval (e.g., "http://localhost:8000")
        ttl_seconds: How long the URL should be valid
        preview_chars: Number of characters to include in preview

    Returns:
        CachedOutputResponse with token, URL, preview, etc.
    """
    ensure_cache_dir()

    token = generate_token()
    expires_at = int(time.time()) + ttl_seconds
    signature = sign_url(token, expires_at, secret)

    # Write content to cache file
    cache_path = CACHE_DIR / f"{token}.txt"
    cache_path.write_text(content)

    # Create ISO 8601 timestamp for expires_at
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Build retrieval URL
    base = base_url.rstrip("/")
    retrieve_url = f"{base}/cache/{token}?expires={expires_at}&sig={signature}"

    # Create preview
    if len(content) > preview_chars:
        preview = content[:preview_chars] + "..."
    else:
        preview = content

    return CachedOutputResponse(
        cached=True,
        token=token,
        retrieve_url=retrieve_url,
        expires_at=expires_at_iso,
        preview=preview,
        size_bytes=len(content.encode("utf-8")),
    )


def verify_and_retrieve(
    token: str, expires_at: int, signature: str, secret: str
) -> str | None:
    """Verify signature and retrieve cached content.

    This function is used by both the HTTP endpoint and the
    retrieve_cached_output tool.

    Args:
        token: The cache token
        expires_at: Unix timestamp when URL expires
        signature: The HMAC signature
        secret: HMAC signing secret

    Returns:
        The cached content if valid, None otherwise
    """
    # Verify signature
    if not verify_signature(token, expires_at, signature, secret):
        return None

    # Check expiration
    if time.time() > expires_at:
        return None

    # Retrieve content
    cache_path = CACHE_DIR / f"{token}.txt"
    if not cache_path.exists():
        return None

    return cache_path.read_text()


def retrieve_by_token(token: str, secret: str) -> str | None:
    """Retrieve cached content by token only (for retrieve_cached_output tool).

    This reads the metadata from a companion file to get expiration and signature,
    then validates and returns the content.

    For the tool-based retrieval, we store expiration info alongside the content
    so the LLM only needs to provide the token.

    Args:
        token: The cache token
        secret: HMAC signing secret

    Returns:
        The cached content if valid and not expired, None otherwise
    """
    meta_path = CACHE_DIR / f"{token}.meta"
    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text())
        expires_at = meta["expires_at"]
        signature = meta["signature"]
    except (json.JSONDecodeError, KeyError):
        return None

    return verify_and_retrieve(token, expires_at, signature, secret)


def create_cached_output_with_meta(
    content: str,
    secret: str,
    base_url: str,
    ttl_seconds: int,
    preview_chars: int,
) -> CachedOutputResponse:
    """Cache tool output with metadata file for token-only retrieval.

    This is the main entry point for caching. It creates both the content file
    and a metadata file so the retrieve_cached_output tool can work with just
    the token.

    Args:
        content: The content to cache
        secret: HMAC signing secret
        base_url: Base URL for cache retrieval
        ttl_seconds: How long the URL should be valid
        preview_chars: Number of characters to include in preview

    Returns:
        CachedOutputResponse with token, URL, preview, etc.
    """
    ensure_cache_dir()

    token = generate_token()
    expires_at = int(time.time()) + ttl_seconds
    signature = sign_url(token, expires_at, secret)

    # Write content to cache file
    cache_path = CACHE_DIR / f"{token}.txt"
    cache_path.write_text(content)

    # Write metadata for token-only retrieval
    meta_path = CACHE_DIR / f"{token}.meta"
    meta_path.write_text(json.dumps({"expires_at": expires_at, "signature": signature}))

    # Create ISO 8601 timestamp
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    # Build retrieval URL
    base = base_url.rstrip("/")
    retrieve_url = f"{base}/cache/{token}?expires={expires_at}&sig={signature}"

    # Create preview
    if len(content) > preview_chars:
        preview = content[:preview_chars] + "..."
    else:
        preview = content

    return CachedOutputResponse(
        cached=True,
        token=token,
        retrieve_url=retrieve_url,
        expires_at=expires_at_iso,
        preview=preview,
        size_bytes=len(content.encode("utf-8")),
    )


def clear_cache() -> int:
    """Clear all cached outputs.

    Returns:
        Number of files deleted
    """
    if not CACHE_DIR.exists():
        return 0

    count = 0
    for path in CACHE_DIR.iterdir():
        if path.is_file():
            path.unlink()
            count += 1

    return count


def create_cache_routes(secret: str, path_prefix: str = "") -> list:
    """Create Starlette routes for cache retrieval.

    Args:
        secret: HMAC signing secret for URL verification
        path_prefix: Optional path prefix for the route (e.g., "/mcp")

    Returns:
        List of Starlette Route objects
    """
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

    def parse_optional_int(value: str | None, name: str) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Invalid {name} parameter") from None

    async def retrieve_cache(request: Request) -> Response:
        """HTTP endpoint to retrieve cached output."""
        token = request.path_params["token"]

        # Get query parameters
        expires_str = request.query_params.get("expires")
        signature = request.query_params.get("sig")

        if not expires_str or not signature:
            return PlainTextResponse(
                "Missing expires or sig parameter", status_code=400
            )

        try:
            expires_at = int(expires_str)
        except ValueError:
            return PlainTextResponse("Invalid expires parameter", status_code=400)

        content = verify_and_retrieve(token, expires_at, signature, secret)

        if content is None:
            return PlainTextResponse(
                "Not found, expired, or invalid signature", status_code=404
            )

        try:
            line_offset = parse_optional_int(
                request.query_params.get("line_offset"), "line_offset"
            )
            line_count = parse_optional_int(
                request.query_params.get("line_count"), "line_count"
            )
        except ValueError as exc:
            return PlainTextResponse(str(exc), status_code=400)

        jmespath_expression = request.query_params.get("jmespath_expression")
        if jmespath_expression is None:
            jmespath_expression = request.query_params.get("jmespath")

        payload = build_cached_output_payload(
            content,
            line_offset=line_offset or 0,
            line_count=line_count,
            jmespath_expression=jmespath_expression,
        )
        if "error" in payload:
            return PlainTextResponse(payload["error"], status_code=400)

        return PlainTextResponse(payload["content"])

    return [Route(f"{path_prefix}/cache/{{token}}", retrieve_cache, methods=["GET"])]
