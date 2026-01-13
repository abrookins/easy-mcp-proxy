"""Authentication for MCP Proxy HTTP endpoints.

This module provides authentication support for the MCP proxy, including:
- Static API token authentication (simple bearer tokens)
- OIDC/Auth0 authentication (OAuth 2.1 flows)
- Composite authentication (try static tokens first, fall back to OIDC)

## Environment Variables

### Static Token Authentication (simplest)

Set this to enable simple API token authentication:

- MCP_PROXY_AUTH_TOKENS: Semicolon-separated list of token configurations

Token format (semicolon-separated entries):
- Simple: "token" - just the token, auto-generated client_id, no scopes
- With client_id: "token:my-client" - token with custom client_id
- With scopes: "token:my-client:read,write" - token with client_id and scopes

Examples:
    # Simple tokens (no scopes)
    export MCP_PROXY_AUTH_TOKENS="token-1;token-2;my-secret-key"

    # Tokens with client IDs and scopes
    export MCP_PROXY_AUTH_TOKENS="admin-key:admin:read,write;reader-key:reader:read"

Clients authenticate with: `Authorization: Bearer token-1`

### OIDC/Auth0 Authentication

Set these environment variables to enable Auth0/OIDC authentication:

- FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL: Auth0 OIDC configuration URL
  (e.g., https://your-tenant.auth0.com/.well-known/openid-configuration)
- FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID: Auth0 application client ID
- FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET: Auth0 application client secret
- FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE: Auth0 API audience
- FASTMCP_SERVER_AUTH_AUTH0_BASE_URL: Public URL where your proxy is accessible

### Combined Authentication

If both static tokens AND OIDC are configured, the proxy will:
1. First check if the token matches a static token
2. If not, validate via OIDC

This allows API tokens for programmatic access alongside OAuth for users.

## Usage

    from mcp_proxy.auth import create_auth_provider

    auth = create_auth_provider()
    if auth:
        mcp = FastMCP("My Server", auth=auth)
    else:
        mcp = FastMCP("My Server")  # No auth
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AccessToken, AuthProvider

# Environment variable names
AUTH_TOKENS_VAR = "MCP_PROXY_AUTH_TOKENS"
AUTH0_CONFIG_URL_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL"
AUTH0_CLIENT_ID_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID"
AUTH0_CLIENT_SECRET_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET"
AUTH0_AUDIENCE_VAR = "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE"
AUTH0_BASE_URL_VAR = "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL"


def parse_token_config(token_str: str) -> tuple[str, dict]:
    """Parse a token string into token and metadata.

    Supports two formats:
    1. Simple: "my-token" -> token with auto-generated client_id, no scopes
    2. Extended: "my-token:client_id:scope1,scope2" -> token with custom claims

    Returns:
        Tuple of (token, metadata_dict)
    """
    parts = token_str.strip().split(":")
    token = parts[0]

    if len(parts) == 1:
        # Simple format: just the token
        return token, {
            "client_id": f"static-{hash(token) % 10000:04d}",
            "scopes": [],
        }

    # Extended format: token:client_id or token:client_id:scopes
    client_id = parts[1] if parts[1] else f"static-{hash(token) % 10000:04d}"
    scopes = []
    if len(parts) >= 3 and parts[2]:
        scopes = [s.strip() for s in parts[2].split(",") if s.strip()]
    return token, {
        "client_id": client_id,
        "scopes": scopes,
    }


def get_static_tokens() -> list[str]:
    """Get list of static tokens from environment variable.

    Returns an empty list if MCP_PROXY_AUTH_TOKENS is not set.
    Tokens can include metadata (client_id:scopes) but this returns just tokens.
    """
    tokens_env = os.environ.get(AUTH_TOKENS_VAR, "")
    if not tokens_env:
        return []
    # Split by semicolon for multiple tokens (colon is used for metadata)
    raw_tokens = [t.strip() for t in tokens_env.split(";") if t.strip()]
    # Return just the token part (before any colon)
    return [t.split(":")[0] for t in raw_tokens]


def get_static_token_configs() -> dict[str, dict]:
    """Get static tokens with their full configuration.

    Returns a dict mapping token -> {client_id, scopes} suitable for
    StaticTokenVerifier.
    """
    tokens_env = os.environ.get(AUTH_TOKENS_VAR, "")
    if not tokens_env:
        return {}
    # Split by semicolon for multiple tokens
    raw_tokens = [t.strip() for t in tokens_env.split(";") if t.strip()]
    result = {}
    for raw in raw_tokens:
        token, config = parse_token_config(raw)
        if token:
            result[token] = config
    return result


def is_static_auth_configured() -> bool:
    """Check if static token authentication is configured."""
    return len(get_static_tokens()) > 0


def is_oidc_auth_configured() -> bool:
    """Check if OIDC/Auth0 authentication is configured via environment variables.

    Returns True if all required Auth0 environment variables are set.
    """
    required_vars = [
        AUTH0_CONFIG_URL_VAR,
        AUTH0_CLIENT_ID_VAR,
        AUTH0_CLIENT_SECRET_VAR,
        AUTH0_AUDIENCE_VAR,
        AUTH0_BASE_URL_VAR,
    ]
    return all(os.environ.get(var) for var in required_vars)


def is_auth_configured() -> bool:
    """Check if any authentication is configured.

    Returns True if static tokens OR OIDC is configured.
    """
    return is_static_auth_configured() or is_oidc_auth_configured()


def _create_static_token_provider() -> "AuthProvider":
    """Create a static token provider using FastMCP's StaticTokenVerifier."""
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    # Get full token configs with client_id and scopes
    token_dict = get_static_token_configs()
    return StaticTokenVerifier(tokens=token_dict)


def _create_oidc_provider() -> "AuthProvider":
    """Create an OIDC provider from environment variables."""
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    # Parse required_scopes - None means no scope checking
    scopes_env = os.environ.get("FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES", "")
    if scopes_env:
        required_scopes = [s.strip() for s in scopes_env.split(",") if s.strip()]
    else:
        required_scopes = None

    return OIDCProxy(
        config_url=os.environ.get(AUTH0_CONFIG_URL_VAR),
        client_id=os.environ.get(AUTH0_CLIENT_ID_VAR),
        client_secret=os.environ.get(AUTH0_CLIENT_SECRET_VAR),
        audience=os.environ.get(AUTH0_AUDIENCE_VAR),
        base_url=os.environ.get(AUTH0_BASE_URL_VAR),
        required_scopes=required_scopes,
    )


class CompositeAuthProvider:
    """Auth provider that tries multiple providers in order.

    Tries static token auth first, then falls back to OIDC.
    This allows simple API tokens alongside OAuth for users.

    Implements the full AuthProvider interface required by FastMCP's http_app().
    """

    def __init__(
        self,
        static_provider: "AuthProvider | None" = None,
        oidc_provider: "AuthProvider | None" = None,
    ):
        self.static_provider = static_provider
        self.oidc_provider = oidc_provider

    @property
    def required_scopes(self) -> list[str]:
        """Get required scopes from the underlying providers.

        Returns scopes from OIDC provider if available, otherwise from static provider.
        """
        if self.oidc_provider and hasattr(self.oidc_provider, "required_scopes"):
            return self.oidc_provider.required_scopes or []
        if self.static_provider and hasattr(self.static_provider, "required_scopes"):
            return self.static_provider.required_scopes or []
        return []

    @property
    def base_url(self):
        """Get base_url from OIDC provider if available."""
        if self.oidc_provider and hasattr(self.oidc_provider, "base_url"):
            return self.oidc_provider.base_url
        if self.static_provider and hasattr(self.static_provider, "base_url"):
            return self.static_provider.base_url
        return None

    def _get_resource_url(self, path: str | None = None):
        """Get the resource URL for protected resource metadata.

        Delegates to OIDC provider if available, otherwise constructs from base_url.
        This is required by FastMCP's http_app() when auth is enabled.
        """
        # Try OIDC provider first (it has full OAuth support)
        if self.oidc_provider and hasattr(self.oidc_provider, "_get_resource_url"):
            return self.oidc_provider._get_resource_url(path)

        # Try static provider
        if self.static_provider and hasattr(self.static_provider, "_get_resource_url"):
            return self.static_provider._get_resource_url(path)

        # Fallback: construct from base_url if available
        base = self.base_url
        if base is None:
            return None

        if path:
            from pydantic import AnyHttpUrl

            prefix = str(base).rstrip("/")
            suffix = path.lstrip("/")
            return AnyHttpUrl(f"{prefix}/{suffix}")
        return base

    async def verify_token(self, token: str) -> "AccessToken | None":
        """Verify token against static tokens first, then OIDC."""
        # Try static token first (fast path)
        if self.static_provider:
            result = await self.static_provider.verify_token(token)
            if result is not None:
                return result

        # Fall back to OIDC
        if self.oidc_provider:
            return await self.oidc_provider.verify_token(token)

        return None

    def get_routes(self, mcp_path: str | None = None) -> list:
        """Get routes from OIDC provider (static tokens don't need routes)."""
        if self.oidc_provider and hasattr(self.oidc_provider, "get_routes"):
            return self.oidc_provider.get_routes(mcp_path)
        return []

    def get_well_known_routes(self, mcp_path: str | None = None) -> list:
        """Get well-known routes from OIDC provider."""
        if self.oidc_provider and hasattr(self.oidc_provider, "get_well_known_routes"):
            return self.oidc_provider.get_well_known_routes(mcp_path)
        return []

    def get_middleware(self) -> list:
        """Get middleware that uses this composite provider for token verification.

        This is critical: we must use `self` as the token verifier, not delegate
        to underlying providers. Otherwise, static tokens won't be checked when
        both OIDC and static auth are configured.
        """
        from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
        from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
        from starlette.middleware import Middleware
        from starlette.middleware.authentication import AuthenticationMiddleware

        return [
            Middleware(
                AuthenticationMiddleware,
                backend=BearerAuthBackend(self),  # Use composite provider, not OIDC
            ),
            Middleware(AuthContextMiddleware),
        ]


def create_auth_provider() -> "AuthProvider | None":
    """Create an auth provider from environment variables.

    Returns None if no authentication is configured.

    Supports three modes:
    1. Static tokens only (MCP_PROXY_AUTH_TOKENS)
    2. OIDC only (FASTMCP_SERVER_AUTH_AUTH0_* vars)
    3. Both (tries static tokens first, falls back to OIDC)

    Environment variables:
    - MCP_PROXY_AUTH_TOKENS: Comma-separated list of valid API tokens
    - FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL: Auth0 OIDC configuration URL
    - FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID: Auth0 client ID
    - FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET: Auth0 client secret
    - FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE: Auth0 API audience
    - FASTMCP_SERVER_AUTH_AUTH0_BASE_URL: Public URL of your proxy
    - FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES: Comma-separated scopes (optional)
    """
    has_static = is_static_auth_configured()
    has_oidc = is_oidc_auth_configured()

    if not has_static and not has_oidc:
        return None

    # Create providers as needed
    static_provider = _create_static_token_provider() if has_static else None
    oidc_provider = _create_oidc_provider() if has_oidc else None

    # If only one is configured, return it directly
    if has_static and not has_oidc:
        return static_provider
    if has_oidc and not has_static:
        return oidc_provider

    # Both configured - use composite
    return CompositeAuthProvider(
        static_provider=static_provider,
        oidc_provider=oidc_provider,
    )
