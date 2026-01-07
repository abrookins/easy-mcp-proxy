"""Authentication for MCP Proxy HTTP endpoints.

This module provides a simple wrapper around FastMCP's Auth0Provider.
Authentication is handled entirely by FastMCP - this module just provides
a helper function to create the provider from environment variables.

## Environment Variables

Set these environment variables to enable Auth0 authentication:

- FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL: Auth0 OIDC configuration URL
  (e.g., https://your-tenant.auth0.com/.well-known/openid-configuration)
- FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID: Auth0 application client ID
- FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET: Auth0 application client secret
- FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE: Auth0 API audience
- FASTMCP_SERVER_AUTH_AUTH0_BASE_URL: Public URL where your proxy is accessible

## Usage

When these environment variables are set, call `create_auth_provider()` to get
an Auth0Provider instance that can be passed to FastMCP:

    from mcp_proxy.auth import create_auth_provider

    auth = create_auth_provider()
    if auth:
        mcp = FastMCP("My Server", auth=auth)
    else:
        mcp = FastMCP("My Server")  # No auth

FastMCP's Auth0Provider handles:
- OAuth 2.1 Authorization Code flow with PKCE
- Dynamic Client Registration
- User consent screens (prevents unauthorized client access)
- Token validation
- OAuth discovery endpoints
"""

from __future__ import annotations

import os

# Environment variable names for Auth0 configuration
AUTH0_CONFIG_URL_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL"
AUTH0_CLIENT_ID_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID"
AUTH0_CLIENT_SECRET_VAR = "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET"
AUTH0_AUDIENCE_VAR = "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE"
AUTH0_BASE_URL_VAR = "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL"


def is_auth_configured() -> bool:
    """Check if Auth0 authentication is configured via environment variables.

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


def create_auth_provider():
    """Create an OIDC auth provider from environment variables.

    Returns None if the required environment variables are not set.

    Required environment variables:
    - FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL
    - FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID
    - FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET
    - FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE
    - FASTMCP_SERVER_AUTH_AUTH0_BASE_URL

    Optional:
    - FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES: Comma-separated scopes
      (default: no scope requirement)

    Returns:
        OIDCProxy instance or None if not configured

    Note:
        We use OIDCProxy directly instead of Auth0Provider to work around
        a bug in FastMCP where Auth0Provider defaults to requiring ["openid"]
        scope even when an empty list is specified.
    """
    if not is_auth_configured():
        return None

    # Import here to avoid import errors if fastmcp isn't installed
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    # Parse required_scopes - None means no scope checking
    scopes_env = os.environ.get("FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES", "")
    if scopes_env:
        required_scopes = [s.strip() for s in scopes_env.split(",") if s.strip()]
    else:
        # Empty means no scope requirement
        required_scopes = None

    # Get all required settings from env
    config_url = os.environ.get(AUTH0_CONFIG_URL_VAR)
    client_id = os.environ.get(AUTH0_CLIENT_ID_VAR)
    client_secret = os.environ.get(AUTH0_CLIENT_SECRET_VAR)
    audience = os.environ.get(AUTH0_AUDIENCE_VAR)
    base_url = os.environ.get(AUTH0_BASE_URL_VAR)

    # Use OIDCProxy directly to avoid Auth0Provider's default scope behavior
    return OIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret=client_secret,
        audience=audience,
        base_url=base_url,
        required_scopes=required_scopes,
    )
