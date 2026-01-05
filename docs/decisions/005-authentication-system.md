# ADR-005: HTTP Authentication System

## Status

Accepted

## Context

After implementing the MCP Memory system (ADR-004), a need arose for securing HTTP endpoints when deploying the proxy as a remote service. MCP clients like Claude.ai require OAuth-compatible authentication flows. This work was implemented on January 4-5, 2026.

## Key Decisions

### 1. Dual Authentication Strategy

**Problem**: Different deployment scenarios require different authentication approaches:
- Personal/development use: Simple credentials without external dependencies
- Production use: Integration with existing identity providers (Auth0, Okta, etc.)

**Solution**: Created two authentication providers implementing a common interface:

```python
class AuthProvider(ABC):
    def get_validator(self) -> TokenValidator: ...
    def get_routes(self) -> list[Route]: ...
    def get_excluded_paths(self) -> list[str]: ...
```

| Provider | Use Case | Token Validation |
|----------|----------|------------------|
| `StaticAuthProvider` | Development/personal | base64(client_id:client_secret) |
| `OAuthProvider` | Production | External identity provider |

### 2. MCP-Compliant OAuth Implementation

**Problem**: MCP clients (like Claude.ai) expect full OAuth 2.1 Authorization Code flow with PKCE, not just simple token validation.

**Solution**: `StaticAuthProvider` implements the complete MCP authorization specification:

1. **OAuth 2.0 Authorization Server Metadata (RFC 8414)**
   - `/.well-known/oauth-authorization-server` endpoint
   
2. **OAuth 2.0 Protected Resource Metadata (RFC 9728)**
   - `/.well-known/oauth-protected-resource` endpoint
   - WWW-Authenticate header includes `resource_metadata` URL
   
3. **Dynamic Client Registration (RFC 7591)**
   - `/register` endpoint for client registration
   - Returns pre-configured static credentials to all registrants
   
4. **Authorization Code flow with PKCE (OAuth 2.1)**
   - `/authorize` endpoint with PKCE code challenge
   - `/oauth/token` endpoint for code exchange
   - S256 code challenge method required

### 3. Client ID Metadata Documents (CIMD) Support

**Problem**: MCP spec allows clients to use HTTPS URLs as client_id, with metadata fetched from that URL.

**Solution**: Implemented CIMD support in the authorize endpoint:

```python
# If client_id starts with https://, fetch metadata from that URL
cimd_metadata = await fetch_cimd_metadata(client_id_url, cache, debug)
# Validate redirect_uri against CIMD metadata
if redirect_uri not in cimd_metadata.redirect_uris:
    return JSONResponse({"error": "invalid_request"}, status_code=400)
```

**Security measures**:
- HTTPS required (no HTTP client_id URLs)
- SSRF protection: blocks localhost, 127.0.0.1, private IP ranges
- Metadata cached for 24 hours per MCP spec
- `client_id` in document must match URL exactly

### 4. Configuration-Based Auth

**Problem**: Need to enable authentication declaratively via configuration file.

**Solution**: Added `AuthConfig` model and `auth` field on `ProxyConfig`:

```yaml
# mcp-proxy.yaml
auth:
  client_id: "my-client-id"
  client_secret: "${MCP_PROXY_CLIENT_SECRET}"  # Environment variable
  issuer_url: "https://mcp.example.com"         # For OAuth discovery
  # Optional: for external OAuth provider
  # token_url: "https://auth.example.com/oauth/token"
  # scopes: ["read", "write"]
  # audience: "https://api.example.com"
```

**Behavior**:
- No `token_url`: Uses `StaticAuthProvider` (internal validation)
- With `token_url`: Uses `OAuthProvider` (external validation)

### 5. CLI Auth Flags

**Addition**: `--auth` flag and OAuth options for the serve command:

```bash
# Simple static auth (reads from environment)
export MCP_PROXY_AUTH_CLIENT_ID="my-client"
export MCP_PROXY_AUTH_CLIENT_SECRET="my-secret"
mcp-proxy serve --transport http --auth

# With custom issuer URL for OAuth discovery
mcp-proxy serve --transport http --auth --issuer-url https://mcp.example.com
```

### 6. Auth Middleware Integration

**Implementation**: `AuthMiddleware` wraps the Starlette app:

```python
app = AuthMiddleware(
    app,
    validator=auth_provider.get_validator(),
    exclude_paths=["/health", "/.well-known/", "/oauth/", "/authorize", "/register"],
    resource_metadata_url=auth_provider.get_resource_metadata_url(),
)
```

**Key behaviors**:
- Returns 401 with `WWW-Authenticate` header on missing/invalid token
- Skips auth for excluded paths (OAuth endpoints must be public)
- Supports both Bearer token and HTTP Basic authentication

### 7. Programmatic Auth API

**Addition**: `run_with_static_auth()` method on `MCPProxy`:

```python
proxy = MCPProxy(config)
proxy.run_with_static_auth(
    client_id="my-client",
    client_secret="my-secret",
    port=8000,
    issuer_url="https://mcp.example.com",
)
```

## Architecture

```
mcp_proxy/
└── auth.py                  # All auth components (~950 lines)
    ├── TokenValidator       # Protocol for token validation
    ├── AuthProvider         # Abstract base for providers
    ├── StaticTokenValidator # Validates base64(client_id:client_secret)
    ├── StaticAuthProvider   # Full OAuth server with static credentials
    ├── OAuthTokenValidator  # Validates against external provider
    ├── OAuthProvider        # External identity provider integration
    └── AuthMiddleware       # Starlette middleware for request validation
```

## Security Considerations

1. **Constant-time token comparison**: Prevents timing attacks
2. **PKCE required**: No authorization code flow without code_challenge
3. **SSRF protection**: CIMD fetches block internal addresses
4. **One-time auth codes**: Codes deleted after exchange
5. **10-minute code expiry**: Short-lived authorization codes

## Dependencies Added

```toml
dependencies = [
    "httpx>=0.24.0",  # For CIMD fetching and OAuth token validation
]
```

## Consequences

- MCP clients (Claude.ai) can authenticate via standard OAuth flow
- Simple deployment with static credentials for personal use
- Production-ready integration with external identity providers
- Complete RFC compliance for OAuth discovery
- Auth configuration via YAML or CLI flags
- Comprehensive test coverage maintained (100% requirement)

