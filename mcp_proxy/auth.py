"""Authentication providers for MCP Proxy HTTP endpoints.

This module provides two authentication strategies:

1. **StaticAuthProvider**: MCP-compliant OAuth with static credential validation.
   - Implements full OAuth 2.1 Authorization Code flow with PKCE
   - Supports Dynamic Client Registration (RFC 7591)
   - Serves OAuth discovery endpoints (RFC 8414)
   - Validates tokens internally (no external OAuth provider needed)
   - Best for personal/development use with MCP clients like Claude.ai

2. **OAuthProvider**: Full OAuth 2.0 with an external identity provider.
   - Validates tokens against a real OAuth provider (Auth0, Okta, etc.)
   - Supports token introspection or client credentials validation
   - Best for production deployments with existing identity infrastructure

Both providers implement the same interface and can be used interchangeably
with the AuthMiddleware.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import httpx
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.types import ASGIApp


# =============================================================================
# Protocol / Interface
# =============================================================================


class TokenValidator(Protocol):
    """Protocol for token validation strategies."""

    async def validate_token(self, token: str) -> bool:
        """Validate an access token. Returns True if valid."""
        ...

    def extract_token(self, request: Request) -> str | None:
        """Extract token from request. Returns None if not present."""
        ...


class AuthProvider(ABC):
    """Base class for authentication providers.

    An auth provider handles:
    1. Token validation (via a TokenValidator)
    2. Optional OAuth routes (discovery, token endpoint)
    3. Paths to exclude from authentication
    """

    @abstractmethod
    def get_validator(self) -> TokenValidator:
        """Get the token validator for this provider."""
        ...

    @abstractmethod
    def get_routes(self) -> list[Route]:
        """Get OAuth routes (discovery, token endpoints). May be empty."""
        ...

    @abstractmethod
    def get_excluded_paths(self) -> list[str]:
        """Get paths that should be excluded from authentication."""
        ...


# =============================================================================
# Static Auth Provider (OAuth-compatible endpoints, static credential validation)
# =============================================================================


@dataclass
class StaticTokenValidator:
    """Validates tokens as base64(client_id:client_secret).

    Accepts either:
    - Bearer token: Base64-encoded "client_id:client_secret"
    - Basic auth: Standard HTTP Basic Authentication header
    """

    client_id: str
    client_secret: str
    debug: bool = False

    def _generate_token(self) -> str:
        """Generate the expected token from credentials."""
        credentials = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(credentials.encode()).decode()

    async def validate_token(self, token: str) -> bool:
        """Validate that the token matches our credentials."""
        expected = self._generate_token()
        if self.debug:
            import logging

            logging.info(f"[AUTH DEBUG] Received token: {token[:20]}...")
            logging.info(f"[AUTH DEBUG] Expected token: {expected[:20]}...")
        # Use constant-time comparison to prevent timing attacks
        return (
            hashlib.sha256(token.encode()).digest()
            == hashlib.sha256(expected.encode()).digest()
        )

    def extract_token(self, request: Request) -> str | None:
        """Extract token from Authorization header (Bearer or Basic)."""
        auth_header = request.headers.get("authorization", "")

        if self.debug:
            import logging

            header_preview = auth_header[:50] if auth_header else "None"
            logging.info(f"[AUTH DEBUG] Auth header: {header_preview}...")
            logging.info(f"[AUTH DEBUG] All headers: {dict(request.headers)}")

        if auth_header.lower().startswith("bearer "):
            return auth_header[7:]
        elif auth_header.lower().startswith("basic "):
            # Basic auth is already base64 encoded client_id:client_secret
            return auth_header[6:]

        return None


@dataclass
class AuthorizationCode:
    """Stored authorization code with PKCE verifier."""

    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    scope: str
    expires_at: float


@dataclass
class RegisteredClient:
    """Dynamically registered OAuth client."""

    client_id: str
    client_secret: str
    redirect_uris: list[str]
    client_name: str | None = None


@dataclass
class CIMDMetadata:
    """Cached Client ID Metadata Document (CIMD).

    Per MCP spec, when client_id is an HTTPS URL, the server fetches
    the metadata document from that URL to get client information.
    """

    client_id: str  # The URL itself
    client_name: str | None
    redirect_uris: list[str]
    fetched_at: float
    # Cache for 24 hours per MCP spec recommendation
    cache_ttl: float = 86400.0


async def fetch_cimd_metadata(
    client_id_url: str,
    cache: dict[str, CIMDMetadata],
    debug: bool = False,
) -> CIMDMetadata | None:
    """Fetch Client ID Metadata Document from an HTTPS URL.

    Per MCP spec (draft-ietf-oauth-client-id-metadata-document-00):
    - client_id is an HTTPS URL pointing to a JSON metadata document
    - The document must contain client_id matching the URL exactly
    - redirect_uris in the document are authoritative

    Returns None if fetch fails or validation fails.
    """
    # Check cache first
    if client_id_url in cache:
        cached = cache[client_id_url]
        if time.time() - cached.fetched_at < cached.cache_ttl:
            return cached

    # Validate URL format
    if not client_id_url.startswith("https://"):
        if debug:
            import logging

            logging.info(f"[CIMD] Rejecting non-HTTPS client_id: {client_id_url}")
        return None

    # SSRF protection: block internal/loopback addresses
    try:
        parsed = urllib.parse.urlparse(client_id_url)
        hostname = parsed.hostname or ""
        if (
            hostname in ("localhost", "127.0.0.1", "::1")
            or hostname.startswith("192.168.")
            or hostname.startswith("10.")
            or hostname.startswith("169.254.")
        ):
            if debug:
                import logging

                logging.info(f"[CIMD] Blocking internal address: {hostname}")
            return None
    except Exception:  # pragma: no cover
        return None  # pragma: no cover

    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.get(client_id_url)
            if resp.status_code != 200:
                if debug:  # pragma: no branch
                    import logging

                    logging.info(
                        f"[CIMD] Failed to fetch {client_id_url}: {resp.status_code}"
                    )
                return None

            data = resp.json()

            # Validate client_id matches URL exactly
            if data.get("client_id") != client_id_url:
                if debug:
                    import logging

                    doc_id = data.get("client_id")
                    logging.info(f"[CIMD] client_id mismatch: {doc_id}")
                    logging.info(f"[CIMD] Expected: {client_id_url}")
                return None

            # Extract required fields
            redirect_uris = data.get("redirect_uris", [])
            if not isinstance(redirect_uris, list):
                return None

            metadata = CIMDMetadata(
                client_id=client_id_url,
                client_name=data.get("client_name"),
                redirect_uris=redirect_uris,
                fetched_at=time.time(),
            )
            cache[client_id_url] = metadata

            if debug:
                import logging

                client_name = data.get("client_name")
                logging.info(f"[CIMD] Fetched metadata: {client_name}")
                logging.info(f"[CIMD] Client URL: {client_id_url}")

            return metadata

    except Exception as e:
        if debug:
            import logging

            logging.info(f"[CIMD] Error fetching {client_id_url}: {e}")
        return None


@dataclass
class StaticAuthProvider(AuthProvider):
    """MCP-compliant OAuth provider with static credential validation.

    This provider implements the full MCP authorization specification:
    1. OAuth 2.0 Authorization Server Metadata (RFC 8414)
    2. OAuth 2.0 Protected Resource Metadata (RFC 9728)
    3. Dynamic Client Registration (RFC 7591)
    4. Authorization Code flow with PKCE (OAuth 2.1)

    MCP clients (like Claude.ai) can:
    1. Discover OAuth endpoints via /.well-known/oauth-authorization-server
    2. Register dynamically via /register
    3. Authorize via /authorize (with PKCE)
    4. Exchange auth code for token via /oauth/token

    Internally, tokens are validated as base64(client_id:client_secret).

    Usage:
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://my-server.example.com"
        )
        routes = provider.get_routes()
        validator = provider.get_validator()
    """

    client_id: str
    client_secret: str
    issuer_url: str
    debug: bool = False
    # In-memory storage for auth codes, registered clients, and CIMD cache
    _auth_codes: dict[str, AuthorizationCode] = field(default_factory=dict)
    _registered_clients: dict[str, RegisteredClient] = field(default_factory=dict)
    _cimd_cache: dict[str, CIMDMetadata] = field(default_factory=dict)

    def get_validator(self) -> StaticTokenValidator:
        """Get the static token validator."""
        return StaticTokenValidator(
            client_id=self.client_id,
            client_secret=self.client_secret,
            debug=self.debug,
        )

    def get_routes(self) -> list[Route]:
        """Get OAuth-compatible discovery and token routes."""
        return self._create_oauth_routes()

    def get_excluded_paths(self) -> list[str]:
        """Paths excluded from auth (OAuth endpoints must be public)."""
        return ["/health", "/.well-known/", "/oauth/", "/authorize", "/register"]

    def get_resource_metadata_url(self) -> str:
        """Get the OAuth 2.0 Protected Resource Metadata URL (RFC 9728).

        MCP clients use this URL (from WWW-Authenticate header) to discover
        the authorization server.
        """
        return f"{self.issuer_url}/.well-known/oauth-protected-resource"

    def _verify_pkce(
        self, code_verifier: str, code_challenge: str, method: str
    ) -> bool:
        """Verify PKCE code_verifier against stored code_challenge."""
        if method == "S256":
            # SHA256 hash of verifier, base64url encoded
            digest = hashlib.sha256(code_verifier.encode()).digest()
            computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            return computed == code_challenge
        elif method == "plain":
            return code_verifier == code_challenge
        return False

    def _create_oauth_routes(self) -> list[Route]:
        """Create MCP-compliant OAuth endpoints."""
        client_id = self.client_id
        client_secret = self.client_secret
        issuer_url = self.issuer_url
        auth_codes = self._auth_codes
        registered_clients = self._registered_clients
        cimd_cache = self._cimd_cache
        verify_pkce = self._verify_pkce
        debug = self.debug

        async def oauth_metadata(request: Request) -> JSONResponse:
            """Serve OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
            return JSONResponse(
                {
                    "issuer": issuer_url,
                    "authorization_endpoint": f"{issuer_url}/authorize",
                    "token_endpoint": f"{issuer_url}/oauth/token",
                    "registration_endpoint": f"{issuer_url}/register",
                    # Support for Client ID Metadata Documents (CIMD)
                    # per MCP spec - clients can use HTTPS URLs as client_id
                    "client_id_metadata_document_supported": True,
                    "token_endpoint_auth_methods_supported": [
                        "none",  # Public clients (PKCE only)
                        "client_secret_post",
                        "client_secret_basic",
                    ],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                    "scopes_supported": ["mcp:read", "mcp:write", "mcp:admin"],
                }
            )

        async def oauth_protected_resource(request: Request) -> JSONResponse:
            """Serve OAuth 2.0 Protected Resource Metadata (RFC 9728)."""
            return JSONResponse(
                {
                    "resource": issuer_url,
                    "authorization_servers": [issuer_url],
                    "scopes_supported": ["mcp:read", "mcp:write", "mcp:admin"],
                    "bearer_methods_supported": ["header"],
                }
            )

        async def register_endpoint(request: Request) -> JSONResponse:
            """Handle Dynamic Client Registration (RFC 7591).

            MCP clients register to get client credentials. For static auth,
            we return our pre-configured credentials to all registrants.
            """
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "Invalid JSON"},
                    status_code=400,
                )

            redirect_uris = body.get("redirect_uris", [])
            client_name = body.get("client_name", "MCP Client")

            if debug:
                import logging

                logging.info(f"[AUTH] Client registration: {client_name}")
                logging.info(f"[AUTH] Redirect URIs: {redirect_uris}")

            # For static auth, return our pre-configured credentials
            # This allows any MCP client to use our static credentials
            new_client = RegisteredClient(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uris=redirect_uris,
                client_name=client_name,
            )
            registered_clients[client_id] = new_client

            return JSONResponse(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "client_id_issued_at": int(time.time()),
                    "client_secret_expires_at": 0,  # Never expires
                    "redirect_uris": redirect_uris,
                    "client_name": client_name,
                    "token_endpoint_auth_method": "client_secret_post",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
                status_code=201,
            )

        async def authorize_endpoint(
            request: Request,
        ) -> RedirectResponse | JSONResponse:
            """Handle OAuth Authorization requests with PKCE.

            Supports both:
            - Client ID Metadata Documents (CIMD): client_id is an HTTPS URL
            - Dynamic Client Registration (DCR): client_id from /register

            For static auth, we auto-approve and redirect with an auth code.
            In production, this would show a consent screen.
            """
            params = dict(request.query_params)

            response_type = params.get("response_type")
            req_client_id = params.get("client_id")
            redirect_uri = params.get("redirect_uri")
            scope = params.get("scope", "")
            state = params.get("state", "")
            code_challenge = params.get("code_challenge")
            code_challenge_method = params.get("code_challenge_method", "S256")

            if debug:
                import logging

                logging.info(f"[AUTH] Authorize request: client={req_client_id}")
                logging.info(f"[AUTH] Redirect URI: {redirect_uri}")
                logging.info(f"[AUTH] PKCE challenge: {code_challenge}")
                logging.info(f"[AUTH] PKCE method: {code_challenge_method}")

            # Validate required parameters
            if response_type != "code":
                return JSONResponse(
                    {"error": "unsupported_response_type"},
                    status_code=400,
                )

            if not redirect_uri:
                return JSONResponse(
                    {
                        "error": "invalid_request",
                        "error_description": "redirect_uri required",
                    },
                    status_code=400,
                )

            if not code_challenge:
                return JSONResponse(
                    {
                        "error": "invalid_request",
                        "error_description": "code_challenge required (PKCE)",
                    },
                    status_code=400,
                )

            # Handle Client ID Metadata Documents (CIMD)
            # If client_id is an HTTPS URL, fetch metadata and validate redirect_uri
            if req_client_id and req_client_id.startswith("https://"):
                if debug:  # pragma: no branch
                    import logging

                    logging.info(f"[AUTH] CIMD client detected: {req_client_id}")

                cimd_metadata = await fetch_cimd_metadata(
                    req_client_id, cimd_cache, debug
                )
                if cimd_metadata is None:
                    return JSONResponse(
                        {
                            "error": "invalid_client",
                            "error_description": "Failed to fetch client metadata",
                        },
                        status_code=400,
                    )

                # Validate redirect_uri against CIMD metadata
                if redirect_uri not in cimd_metadata.redirect_uris:
                    if debug:  # pragma: no branch
                        import logging

                        logging.info(f"[AUTH] redirect_uri {redirect_uri} invalid")
                        logging.info(f"[AUTH] Allowed: {cimd_metadata.redirect_uris}")
                    return JSONResponse(
                        {
                            "error": "invalid_request",
                            "error_description": "redirect_uri not registered",
                        },
                        status_code=400,
                    )

                if debug:  # pragma: no branch
                    import logging

                    logging.info(f"[AUTH] CIMD validated: {cimd_metadata.client_name}")

            # Generate authorization code
            auth_code = secrets.token_urlsafe(32)
            auth_codes[auth_code] = AuthorizationCode(
                code=auth_code,
                client_id=req_client_id or client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                scope=scope,
                expires_at=time.time() + 600,  # 10 minute expiry
            )

            # Build redirect URL with auth code
            parsed = urllib.parse.urlparse(redirect_uri)
            query_params = urllib.parse.parse_qs(parsed.query)
            query_params["code"] = [auth_code]
            if state:
                query_params["state"] = [state]

            new_query = urllib.parse.urlencode(query_params, doseq=True)
            redirect_url = urllib.parse.urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )

            if debug:
                import logging

                logging.info(f"[AUTH] Redirecting to: {redirect_url}")

            return RedirectResponse(url=redirect_url, status_code=302)

        async def token_endpoint(request: Request) -> JSONResponse:
            """Handle OAuth token requests (authorization_code and refresh_token)."""
            # Parse request body
            try:
                content_type = request.headers.get("content-type", "")
                if content_type.startswith("application/json"):
                    body = await request.json()
                else:
                    form = await request.form()
                    body = dict(form)
            except Exception:
                return JSONResponse(
                    {
                        "error": "invalid_request",
                        "error_description": "Invalid request body",
                    },
                    status_code=400,
                )

            grant_type = body.get("grant_type")

            if debug:
                import logging

                logging.info(f"[AUTH] Token request: grant_type={grant_type}")

            if grant_type == "authorization_code":
                return await _handle_auth_code_grant(body, request)
            elif grant_type == "refresh_token":
                return await _handle_refresh_token_grant(body, request)
            else:
                return JSONResponse(
                    {
                        "error": "unsupported_grant_type",
                        "error_description": f"Unsupported: {grant_type}",
                    },
                    status_code=400,
                )

        async def _handle_auth_code_grant(body: dict, request: Request) -> JSONResponse:
            """Handle authorization_code grant type."""
            code = body.get("code")
            redirect_uri = body.get("redirect_uri")
            code_verifier = body.get("code_verifier")
            # client_id is sent but we use our static credentials

            if debug:
                import logging

                code_preview = code[:20] if code else None
                verifier_preview = code_verifier[:20] if code_verifier else None
                logging.info(f"[AUTH] Auth code exchange: code={code_preview}...")
                logging.info(f"[AUTH] code_verifier={verifier_preview}...")

            # Validate auth code exists
            if not code or code not in auth_codes:
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "Invalid authorization code",
                    },
                    status_code=400,
                )

            stored = auth_codes[code]

            # Check expiry
            if time.time() > stored.expires_at:  # pragma: no branch
                del auth_codes[code]  # pragma: no cover
                return JSONResponse(  # pragma: no cover
                    {
                        "error": "invalid_grant",
                        "error_description": "Authorization code expired",
                    },
                    status_code=400,
                )

            # Validate redirect_uri matches
            if redirect_uri and redirect_uri != stored.redirect_uri:
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "redirect_uri mismatch",
                    },
                    status_code=400,
                )

            # Validate PKCE
            if not code_verifier:
                return JSONResponse(
                    {
                        "error": "invalid_request",
                        "error_description": "code_verifier required",
                    },
                    status_code=400,
                )

            if not verify_pkce(
                code_verifier, stored.code_challenge, stored.code_challenge_method
            ):
                return JSONResponse(
                    {
                        "error": "invalid_grant",
                        "error_description": "PKCE verification failed",
                    },
                    status_code=400,
                )

            # Remove used auth code (one-time use)
            del auth_codes[code]

            # Generate access token
            access_token = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()
            refresh_token = secrets.token_urlsafe(32)

            return JSONResponse(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": refresh_token,
                    "scope": stored.scope or "mcp:read mcp:write",
                }
            )

        async def _handle_refresh_token_grant(
            body: dict, request: Request
        ) -> JSONResponse:
            """Handle refresh_token grant type."""
            # For static auth, just issue a new token
            access_token = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()
            refresh_token = secrets.token_urlsafe(32)

            return JSONResponse(
                {
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": refresh_token,
                    "scope": "mcp:read mcp:write",
                }
            )

        return [
            Route(
                "/.well-known/oauth-authorization-server",
                oauth_metadata,
                methods=["GET"],
            ),
            Route(
                "/.well-known/oauth-protected-resource",
                oauth_protected_resource,
                methods=["GET"],
            ),
            Route("/register", register_endpoint, methods=["POST"]),
            Route("/authorize", authorize_endpoint, methods=["GET"]),
            Route("/oauth/token", token_endpoint, methods=["POST"]),
        ]


# =============================================================================
# OAuth Provider (Real OAuth with external identity provider)
# =============================================================================


@dataclass
class TokenInfo:
    """Cached token information."""

    access_token: str
    expires_at: float
    token_type: str = "Bearer"


@dataclass
class OAuthTokenValidator:
    """Validates OAuth tokens against an external identity provider.

    For client credentials flow, validates by checking if the incoming token
    matches a token we can fetch from the provider. For production use,
    consider implementing token introspection (RFC 7662) instead.
    """

    client_id: str
    client_secret: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    audience: str | None = None
    _cached_tokens: dict[str, TokenInfo] = field(default_factory=dict)

    async def fetch_token(self) -> TokenInfo:
        """Fetch an access token using client credentials flow."""
        async with httpx.AsyncClient() as client:
            data: dict[str, str] = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            if self.scopes:
                data["scope"] = " ".join(self.scopes)
            if self.audience:
                data["audience"] = self.audience

            response = await client.post(self.token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            expires_in = token_data.get("expires_in", 3600)
            return TokenInfo(
                access_token=token_data["access_token"],
                expires_at=time.time() + expires_in - 60,  # 60s buffer
                token_type=token_data.get("token_type", "Bearer"),
            )

    async def validate_token(self, token: str) -> bool:
        """Validate an incoming token against the OAuth provider.

        Currently validates by comparing to a fetched token. For production,
        consider implementing token introspection (RFC 7662).
        """
        cache_key = f"{self.client_id}:{self.client_secret}"
        cached = self._cached_tokens.get(cache_key)

        if cached and cached.expires_at > time.time():
            return token == cached.access_token

        try:
            new_token = await self.fetch_token()
            self._cached_tokens[cache_key] = new_token
            return token == new_token.access_token
        except Exception:
            return False

    def extract_token(self, request: Request) -> str | None:
        """Extract Bearer token from request Authorization header."""
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:]
        return None


@dataclass
class OAuthProvider(AuthProvider):
    """Authentication provider using an external OAuth 2.0 identity provider.

    This provider validates tokens against a real OAuth provider like
    Auth0, Okta, Keycloak, etc.

    Usage:
        provider = OAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/oauth/token",
            scopes=["read", "write"],
        )
        validator = provider.get_validator()
    """

    client_id: str
    client_secret: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    audience: str | None = None

    def get_validator(self) -> OAuthTokenValidator:
        """Get the OAuth token validator."""
        return OAuthTokenValidator(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_url=self.token_url,
            scopes=self.scopes,
            audience=self.audience,
        )

    def get_routes(self) -> list[Route]:
        """No routes needed - OAuth provider handles discovery."""
        return []

    def get_excluded_paths(self) -> list[str]:
        """Only health endpoint excluded."""
        return ["/health"]


# =============================================================================
# Auth Middleware
# =============================================================================


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates tokens on incoming requests.

    Works with any validator that implements the TokenValidator protocol.
    """

    def __init__(
        self,
        app: ASGIApp,
        validator: TokenValidator,
        exclude_paths: list[str] | None = None,
        resource_metadata_url: str | None = None,
    ):
        super().__init__(app)
        self.validator = validator
        self.exclude_paths = exclude_paths or ["/health"]
        self.resource_metadata_url = resource_metadata_url

    def _www_authenticate_header(self) -> str:
        """Build WWW-Authenticate header per MCP spec (RFC 9728).

        MCP clients use the resource_metadata URL to discover the authorization server.
        """
        if self.resource_metadata_url:
            return f'Bearer resource_metadata="{self.resource_metadata_url}"'
        return "Bearer"

    async def dispatch(self, request: Request, call_next):
        """Validate token before passing request to the app."""
        # Skip auth for excluded paths
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        token = self.validator.extract_token(request)
        if not token:
            return JSONResponse(
                {"error": "unauthorized", "message": "Missing authorization header"},
                status_code=401,
                headers={"WWW-Authenticate": self._www_authenticate_header()},
            )

        is_valid = await self.validator.validate_token(token)
        if not is_valid:
            return JSONResponse(
                {"error": "unauthorized", "message": "Invalid or expired token"},
                status_code=401,
                headers={"WWW-Authenticate": self._www_authenticate_header()},
            )

        return await call_next(request)


# =============================================================================
# Backwards Compatibility Aliases
# =============================================================================

# These maintain compatibility with existing code that imports the old names
OAuthValidator = OAuthTokenValidator


def create_oauth_routes(
    client_id: str, client_secret: str, issuer_url: str
) -> list[Route]:
    """Create OAuth discovery and token routes.

    DEPRECATED: Use StaticAuthProvider instead.
    """
    provider = StaticAuthProvider(
        client_id=client_id,
        client_secret=client_secret,
        issuer_url=issuer_url,
    )
    return provider.get_routes()
