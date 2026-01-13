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

from pydantic import BaseModel

# Cache directory in system temp
CACHE_DIR = Path(tempfile.gettempdir()) / "mcp-proxy-cache"


class CachedOutputResponse(BaseModel):
    """Response returned when tool output is cached."""

    cached: bool = True
    token: str
    retrieve_url: str
    expires_at: str  # ISO 8601 timestamp
    preview: str
    size_bytes: int


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


def create_cache_routes(secret: str) -> list:
    """Create Starlette routes for cache retrieval.

    Args:
        secret: HMAC signing secret for URL verification

    Returns:
        List of Starlette Route objects
    """
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

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

        return PlainTextResponse(content)

    return [Route("/cache/{token}", retrieve_cache, methods=["GET"])]
