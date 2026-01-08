# ADR-008: Authentication Simplification and Search Endpoint

## Status

Accepted

## Context

After implementing the full OAuth 2.1 authentication system (ADR-005), two issues emerged:

1. **Auth complexity**: The custom OAuth implementation (~950 lines) duplicated functionality already provided by FastMCP's built-in authentication. This created maintenance burden and potential security risks from maintaining custom OAuth code.

2. **Tool discovery friction**: Users with many upstream servers needed to manually configure views with `exposure_mode: search_per_server` to get search-based tool access. There was no simple way to "just see all tools with search" without explicit configuration.

## Key Decisions

### 1. Delegate Authentication to FastMCP

**Problem**: Custom OAuth implementation was complex, hard to maintain, and duplicated FastMCP's capabilities.

**Solution**: Replaced ~950 lines of custom OAuth code with a thin wrapper (~120 lines) around FastMCP's `OIDCProxy`.

**Before** (ADR-005):
```python
class StaticAuthProvider(AuthProvider):
    # Full OAuth server implementation
    # CIMD support, PKCE validation, token management, etc.
    pass

class OAuthProvider(AuthProvider):
    # External OAuth integration
    pass
```

**After**:
```python
def create_auth_provider():
    """Create OIDC provider from environment variables."""
    if not is_auth_configured():
        return None
    return OIDCProxy(
        config_url=os.environ.get(AUTH0_CONFIG_URL_VAR),
        client_id=os.environ.get(AUTH0_CLIENT_ID_VAR),
        # ... other config from env
    )
```

**Rationale**: 
- FastMCP handles OAuth 2.1, PKCE, Dynamic Client Registration, and token validation
- Fewer lines = fewer bugs and security vulnerabilities
- Environment-based configuration is simpler than YAML for secrets

### 2. Remove AuthConfig from ProxyConfig

**Problem**: YAML-based auth configuration required handling secrets safely.

**Solution**: Auth is now configured entirely via environment variables:

```bash
export FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL="https://tenant.auth0.com/.well-known/openid-configuration"
export FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID="..."
export FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET="..."
export FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE="..."
export FASTMCP_SERVER_AUTH_AUTH0_BASE_URL="https://mcp.example.com"
```

**Rationale**: Environment variables are the standard pattern for secrets in containerized deployments.

### 3. Virtual `/search` Endpoint

**Problem**: Getting search-per-server tool access required explicit view configuration.

**Solution**: Added a built-in `/search/mcp` endpoint that automatically exposes all tools with `search_per_server` mode.

**Implementation**:
```python
def _initialize_search_view(self, mcp: FastMCP) -> None:
    # Create virtual view with include_all + search_per_server
    search_view_config = ToolViewConfig(
        description="All tools with search per server",
        exposure_mode="search_per_server",
        include_all=True,
    )
    search_view = ToolView(name="_search", config=search_view_config)
    self.views["_search"] = search_view
    # Register per-server search tools
    self._register_per_server_search_tools(mcp, "_search")
```

**HTTP endpoints** after this change:
- `/mcp` - Default view (all tools or configured default)
- `/view/<name>/mcp` - Named views from `tool_views`
- `/search/mcp` - **New**: All tools via search_per_server mode

**Rationale**: Users often want search-based access without configuration overhead. The `/search` endpoint provides this out of the box.

### 4. Access Logging Option

**Addition**: `--access-log` flag for the serve command enables uvicorn access logging for debugging HTTP requests.

```bash
mcp-proxy serve --transport http --access-log
```

## Consequences

### Positive
- Auth code reduced from ~950 lines to ~120 lines
- Security maintained via FastMCP's battle-tested OAuth implementation
- `/search` endpoint provides zero-config search-per-server access
- Environment-based auth configuration follows 12-factor app principles
- 100% test coverage maintained

### Trade-offs
- Lost custom StaticAuthProvider (simple base64 tokens)
- Auth now requires external OIDC provider (Auth0, Okta, etc.)
- CLI `--auth` flag removed (auth now auto-detected from env vars)

### Migration

Users of ADR-005's static auth must migrate to an OIDC provider:

**Before**:
```bash
export MCP_PROXY_AUTH_CLIENT_ID="my-client"
export MCP_PROXY_AUTH_CLIENT_SECRET="my-secret"
mcp-proxy serve --auth
```

**After**:
```bash
export FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL="https://..."
export FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID="..."
# ... other Auth0 config
mcp-proxy serve --transport http  # Auth auto-detected
```

