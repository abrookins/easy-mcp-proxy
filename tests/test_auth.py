"""Tests for OAuth authentication module."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_proxy.auth import (
    AuthMiddleware,
    CIMDMetadata,
    OAuthValidator,
    StaticAuthProvider,
    StaticTokenValidator,
    TokenInfo,
    fetch_cimd_metadata,
)


class TestTokenInfo:
    """Tests for TokenInfo dataclass."""

    def test_token_info_creation(self):
        """TokenInfo should store token data."""
        token = TokenInfo(
            access_token="test-token",
            expires_at=time.time() + 3600,
        )
        assert token.access_token == "test-token"
        assert token.token_type == "Bearer"

    def test_token_info_custom_type(self):
        """TokenInfo should accept custom token type."""
        token = TokenInfo(
            access_token="test-token",
            expires_at=time.time() + 3600,
            token_type="MAC",
        )
        assert token.token_type == "MAC"


class TestOAuthValidator:
    """Tests for OAuthValidator class."""

    def test_validator_creation(self):
        """OAuthValidator should be created with required fields."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        assert validator.client_id == "my-client"
        assert validator.scopes == []
        assert validator.audience is None

    def test_validator_with_scopes(self):
        """OAuthValidator should accept scopes."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
            scopes=["read", "write"],
        )
        assert validator.scopes == ["read", "write"]

    def test_extract_token_with_bearer(self):
        """extract_token should extract Bearer token from header."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer test-token-123"}

        token = validator.extract_token(request)
        assert token == "test-token-123"

    def test_extract_token_case_insensitive(self):
        """extract_token should be case-insensitive for Bearer prefix."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "bearer test-token-123"}

        token = validator.extract_token(request)
        assert token == "test-token-123"

    def test_extract_token_missing_header(self):
        """extract_token should return None when header is missing."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        request = MagicMock(spec=Request)
        request.headers = {}

        token = validator.extract_token(request)
        assert token is None

    def test_extract_token_non_bearer(self):
        """extract_token should return None for non-Bearer auth."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Basic dXNlcjpwYXNz"}

        token = validator.extract_token(request)
        assert token is None

    @pytest.mark.asyncio
    async def test_fetch_token_success(self):
        """fetch_token should successfully fetch and return token."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            token = await validator.fetch_token()

            assert token.access_token == "new-token"
            assert token.token_type == "Bearer"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_token_with_scopes(self):
        """fetch_token should include scopes in request."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
            scopes=["read", "write"],
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await validator.fetch_token()

            call_args = mock_client.post.call_args
            assert "scope" in call_args.kwargs["data"]
            assert call_args.kwargs["data"]["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_fetch_token_with_audience(self):
        """fetch_token should include audience in request."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
            audience="https://api.example.com",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await validator.fetch_token()

            call_args = mock_client.post.call_args
            assert "audience" in call_args.kwargs["data"]
            assert call_args.kwargs["data"]["audience"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_validate_token_valid(self):
        """validate_token should return True for valid token."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "valid-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            is_valid = await validator.validate_token("valid-token")
            assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_token_invalid(self):
        """validate_token should return False for invalid token."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "valid-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            is_valid = await validator.validate_token("wrong-token")
            assert is_valid is False

    @pytest.mark.asyncio
    async def test_validate_token_uses_cache(self):
        """validate_token should use cached token if not expired."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        # Pre-populate cache
        cache_key = "my-client:my-secret"
        validator._cached_tokens[cache_key] = TokenInfo(
            access_token="cached-token",
            expires_at=time.time() + 3600,
        )

        is_valid = await validator.validate_token("cached-token")
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_validate_token_expired_cache(self):
        """validate_token should fetch new token if cache expired."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        # Pre-populate with expired cache
        cache_key = "my-client:my-secret"
        validator._cached_tokens[cache_key] = TokenInfo(
            access_token="old-token",
            expires_at=time.time() - 100,  # Expired
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            is_valid = await validator.validate_token("new-token")
            assert is_valid is True
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_token_fetch_error(self):
        """validate_token should return False on fetch error."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            is_valid = await validator.validate_token("any-token")
            assert is_valid is False


class TestAuthMiddleware:
    """Tests for AuthMiddleware class."""

    def _create_test_app(self, validator: OAuthValidator, exclude_paths=None):
        """Create a test Starlette app with auth middleware."""

        async def homepage(request):
            return JSONResponse({"message": "Hello"})

        async def health(request):
            return JSONResponse({"status": "healthy"})

        routes = [
            Route("/", homepage),
            Route("/health", health),
            Route("/api/data", homepage),
        ]
        app = Starlette(routes=routes)
        return AuthMiddleware(app, validator, exclude_paths=exclude_paths)

    def test_middleware_excludes_health(self):
        """Middleware should skip auth for health endpoint."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        app = self._create_test_app(validator)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_middleware_rejects_missing_token(self):
        """Middleware should reject requests without auth header."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        app = self._create_test_app(validator)
        client = TestClient(app)

        response = client.get("/api/data")
        assert response.status_code == 401
        assert "unauthorized" in response.json()["error"]
        assert "WWW-Authenticate" in response.headers

    def test_middleware_rejects_invalid_token(self):
        """Middleware should reject requests with invalid token."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        app = self._create_test_app(validator)
        client = TestClient(app)

        with patch.object(validator, "validate_token", return_value=False):
            response = client.get(
                "/api/data", headers={"Authorization": "Bearer invalid-token"}
            )
            assert response.status_code == 401
            assert "Invalid or expired" in response.json()["message"]

    def test_middleware_accepts_valid_token(self):
        """Middleware should accept requests with valid token."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        app = self._create_test_app(validator)
        client = TestClient(app)

        with patch.object(validator, "validate_token", return_value=True):
            response = client.get(
                "/api/data", headers={"Authorization": "Bearer valid-token"}
            )
            assert response.status_code == 200
            assert response.json()["message"] == "Hello"

    def test_middleware_custom_exclude_paths(self):
        """Middleware should respect custom exclude paths."""
        validator = OAuthValidator(
            client_id="my-client",
            client_secret="my-secret",
            token_url="https://auth.example.com/token",
        )
        # Exclude only /api/data, require auth for everything else
        app = self._create_test_app(validator, exclude_paths=["/api/data"])
        client = TestClient(app)

        # /api/data should be excluded (no auth required)
        response = client.get("/api/data")
        assert response.status_code == 200

        # Root should require auth since it's not excluded
        response = client.get("/")
        assert response.status_code == 401


class TestStaticTokenValidator:
    """Tests for StaticTokenValidator class."""

    def test_validator_creation(self):
        """StaticTokenValidator should be created with credentials."""
        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        assert validator.client_id == "my-client"
        assert validator.client_secret == "my-secret"

    def test_generate_token(self):
        """StaticTokenValidator should generate base64 token."""
        import base64

        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        token = validator._generate_token()
        # Decode and verify
        decoded = base64.b64decode(token).decode()
        assert decoded == "my-client:my-secret"

    @pytest.mark.asyncio
    async def test_validate_token_valid(self):
        """StaticTokenValidator should accept valid token."""
        import base64

        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        token = base64.b64encode(b"my-client:my-secret").decode()
        result = await validator.validate_token(token)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_token_invalid(self):
        """StaticTokenValidator should reject invalid token."""
        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        result = await validator.validate_token("invalid-token")
        assert result is False

    def test_extract_token_bearer(self):
        """StaticTokenValidator should extract Bearer token."""
        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        request = MagicMock()
        request.headers = {"authorization": "Bearer my-token"}
        token = validator.extract_token(request)
        assert token == "my-token"

    def test_extract_token_basic(self):
        """StaticTokenValidator should extract Basic auth credentials."""
        import base64

        validator = StaticTokenValidator(
            client_id="my-client",
            client_secret="my-secret",
        )
        credentials = base64.b64encode(b"my-client:my-secret").decode()
        request = MagicMock()
        request.headers = {"authorization": f"Basic {credentials}"}
        token = validator.extract_token(request)
        assert token == credentials


class TestStaticAuthProvider:
    """Tests for StaticAuthProvider class."""

    def test_provider_creation(self):
        """StaticAuthProvider should be created with credentials."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        assert provider.client_id == "my-client"
        assert provider.issuer_url == "https://example.com"

    def test_get_validator(self):
        """StaticAuthProvider should return StaticTokenValidator."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        validator = provider.get_validator()
        assert isinstance(validator, StaticTokenValidator)
        assert validator.client_id == "my-client"

    def test_get_routes(self):
        """StaticAuthProvider should return OAuth routes."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        assert len(routes) > 0
        # Check for expected routes
        paths = [r.path for r in routes]
        assert "/.well-known/oauth-authorization-server" in paths
        assert "/.well-known/oauth-protected-resource" in paths
        assert "/oauth/token" in paths
        assert "/authorize" in paths
        assert "/register" in paths

    def test_get_excluded_paths(self):
        """StaticAuthProvider should return excluded paths."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        excluded = provider.get_excluded_paths()
        assert "/health" in excluded
        assert "/.well-known/" in excluded

    def test_get_resource_metadata_url(self):
        """StaticAuthProvider should return correct metadata URL."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        url = provider.get_resource_metadata_url()
        assert url == "https://example.com/.well-known/oauth-protected-resource"

    def test_oauth_metadata_endpoint(self):
        """OAuth metadata endpoint should return correct structure."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        data = response.json()
        assert data["issuer"] == "https://example.com"
        assert data["authorization_endpoint"] == "https://example.com/authorize"
        assert data["token_endpoint"] == "https://example.com/oauth/token"
        assert data["client_id_metadata_document_supported"] is True
        assert "none" in data["token_endpoint_auth_methods_supported"]
        assert "S256" in data["code_challenge_methods_supported"]

    def test_protected_resource_endpoint(self):
        """Protected resource endpoint should return correct structure."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        data = response.json()
        assert data["resource"] == "https://example.com"
        assert "https://example.com" in data["authorization_servers"]

    def test_register_endpoint(self):
        """Register endpoint should return client credentials."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.post(
            "/register",
            json={
                "client_name": "Test Client",
                "redirect_uris": ["https://example.com/callback"],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["client_id"] == "my-client"
        assert data["client_secret"] == "my-secret"

    def test_authorize_endpoint_requires_pkce(self):
        """Authorize endpoint should require PKCE code_challenge."""
        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app, follow_redirects=False)

        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "my-client",
                "redirect_uri": "https://example.com/callback",
                # Missing code_challenge
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    def test_authorize_endpoint_with_pkce(self):
        """Authorize endpoint should redirect with code when PKCE provided."""
        import base64
        import hashlib

        provider = StaticAuthProvider(
            client_id="my-client",
            client_secret="my-secret",
            issuer_url="https://example.com",
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app, follow_redirects=False)

        # Generate PKCE verifier and challenge
        verifier = "test-verifier-1234567890123456789012345678901234567890"
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )

        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "my-client",
                "redirect_uri": "https://example.com/callback",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "test-state",
            },
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert "code=" in location
        assert "state=test-state" in location


class TestCIMDMetadata:
    """Tests for CIMDMetadata and fetch_cimd_metadata."""

    def test_cimd_metadata_creation(self):
        """CIMDMetadata should store client metadata."""
        metadata = CIMDMetadata(
            client_id="https://example.com/client",
            client_name="Test Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=time.time(),
        )
        assert metadata.client_id == "https://example.com/client"
        assert metadata.client_name == "Test Client"
        assert len(metadata.redirect_uris) == 1

    @pytest.mark.asyncio
    async def test_fetch_cimd_rejects_non_https(self):
        """fetch_cimd_metadata should reject non-HTTPS URLs."""
        cache: dict[str, CIMDMetadata] = {}
        result = await fetch_cimd_metadata("http://example.com/client", cache)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_cimd_blocks_localhost(self):
        """fetch_cimd_metadata should block localhost (SSRF protection)."""
        cache: dict[str, CIMDMetadata] = {}
        result = await fetch_cimd_metadata("https://localhost/client", cache)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_cimd_blocks_internal_ips(self):
        """fetch_cimd_metadata should block internal IPs (SSRF protection)."""
        cache: dict[str, CIMDMetadata] = {}

        for ip in ["127.0.0.1", "192.168.1.1", "10.0.0.1", "169.254.1.1"]:
            result = await fetch_cimd_metadata(f"https://{ip}/client", cache)
            assert result is None, f"Should block {ip}"

    @pytest.mark.asyncio
    async def test_fetch_cimd_uses_cache(self):
        """fetch_cimd_metadata should return cached metadata."""
        cache: dict[str, CIMDMetadata] = {}
        cached_metadata = CIMDMetadata(
            client_id="https://example.com/client",
            client_name="Cached Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=time.time(),
        )
        cache["https://example.com/client"] = cached_metadata

        result = await fetch_cimd_metadata("https://example.com/client", cache)
        assert result is cached_metadata
        assert result.client_name == "Cached Client"

    @pytest.mark.asyncio
    async def test_fetch_cimd_expired_cache(self):
        """fetch_cimd_metadata should refetch if cache is expired."""
        cache: dict[str, CIMDMetadata] = {}
        # Create expired cached metadata
        cached_metadata = CIMDMetadata(
            client_id="https://example.com/client",
            client_name="Expired Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=time.time() - 100000,  # Long ago
            cache_ttl=1.0,  # 1 second TTL
        )
        cache["https://example.com/client"] = cached_metadata

        # Mock httpx to return new data
        with patch("mcp_proxy.auth.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "client_id": "https://example.com/client",
                "client_name": "Fresh Client",
                "redirect_uris": ["https://example.com/callback"],
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await fetch_cimd_metadata("https://example.com/client", cache)
            assert result is not None
            assert result.client_name == "Fresh Client"

    @pytest.mark.asyncio
    async def test_fetch_cimd_validates_client_id(self):
        """fetch_cimd_metadata should validate client_id matches URL."""
        cache: dict[str, CIMDMetadata] = {}

        with patch("mcp_proxy.auth.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "client_id": "https://different.com/client",  # Doesn't match URL
                "redirect_uris": ["https://example.com/callback"],
            }
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await fetch_cimd_metadata("https://example.com/client", cache)
            assert result is None  # Should fail validation


class TestStaticAuthProviderOAuthFlows:
    """Tests for OAuth authorization flows in StaticAuthProvider."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = StaticAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
        )
        routes = self.provider.get_routes()
        self.app = Starlette(routes=routes)
        self.client = TestClient(self.app)

    def test_authorize_requires_response_type(self):
        """Authorize endpoint should require response_type=code."""
        response = self.client.get("/authorize")
        assert response.status_code == 400
        assert response.json().get("error") == "unsupported_response_type"

    def test_authorize_requires_redirect_uri(self):
        """Authorize endpoint should require redirect_uri."""
        response = self.client.get("/authorize?response_type=code")
        assert response.status_code == 400
        assert "redirect_uri" in response.json().get("error_description", "").lower()

    def test_authorize_requires_code_challenge(self):
        """Authorize endpoint should require code_challenge for PKCE."""
        response = self.client.get(
            "/authorize?response_type=code&client_id=test-client&redirect_uri=https://example.com/callback"
        )
        assert response.status_code == 400
        assert "code_challenge" in response.json().get("error_description", "").lower()

    def test_authorize_redirects_with_auth_code(self):
        """Authorize endpoint should redirect with authorization code."""
        response = self.client.get(
            "/authorize"
            "?client_id=test-client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256"
            "&response_type=code"
            "&state=test-state",
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert "code=" in location
        assert "state=test-state" in location

    def test_token_invalid_grant_type(self):
        """Token endpoint should reject unsupported grant types."""
        response = self.client.post(
            "/oauth/token",
            data={"grant_type": "unsupported"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"

    def test_token_json_body(self):
        """Token endpoint should accept JSON body."""
        response = self.client.post(
            "/oauth/token",
            json={"grant_type": "unsupported"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"

    def test_token_invalid_body(self):
        """Token endpoint should reject invalid request body."""
        response = self.client.post(
            "/oauth/token",
            content=b"\xff\xfe",  # Invalid bytes
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    def test_token_invalid_auth_code(self):
        """Token endpoint should reject invalid authorization codes."""
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "invalid-code",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "test-verifier",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_token_requires_code_verifier(self):
        """Token endpoint should require code_verifier for PKCE."""
        # First get an auth code
        auth_response = self.client.get(
            "/authorize"
            "?client_id=test-client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256"
            "&response_type=code",
            follow_redirects=False,
        )
        location = auth_response.headers["location"]
        import urllib.parse

        parsed = urllib.parse.urlparse(location)
        query = urllib.parse.parse_qs(parsed.query)
        code = query["code"][0]

        # Try to exchange without code_verifier
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
            },
        )
        assert response.status_code == 400
        assert "code_verifier" in response.json().get("error_description", "").lower()

    def test_register_endpoint(self):
        """Register endpoint should handle dynamic client registration."""
        response = self.client.post(
            "/register",
            json={
                "client_name": "Test App",
                "redirect_uris": ["https://example.com/callback"],
            },
        )
        assert response.status_code == 201  # Created
        data = response.json()
        assert "client_id" in data
        assert data["client_name"] == "Test App"

    def test_register_endpoint_invalid_json(self):
        """Register endpoint should reject invalid JSON."""
        response = self.client.post(
            "/register",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    def test_register_endpoint_with_debug(self):
        """Register endpoint should work with debug logging."""
        provider = StaticAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
            debug=True,
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.post(
            "/register",
            json={
                "client_name": "Test App",
                "redirect_uris": ["https://example.com/callback"],
            },
        )
        assert response.status_code == 201

    def test_pkce_plain_method(self):
        """PKCE should support plain code_challenge_method."""
        # Get auth code with plain PKCE
        code_verifier = "test-verifier-plain"
        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=test-client"
            "&redirect_uri=https://example.com/callback"
            f"&code_challenge={code_verifier}"
            "&code_challenge_method=plain",  # Plain method
            follow_redirects=False,
        )
        assert response.status_code == 302

        import urllib.parse

        parsed = urllib.parse.urlparse(response.headers["location"])
        query = urllib.parse.parse_qs(parsed.query)
        code = query["code"][0]

        # Exchange with plain verifier
        token_response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": code_verifier,
            },
        )
        assert token_response.status_code == 200

    def test_pkce_unknown_method(self):
        """PKCE should reject unknown code_challenge_method."""
        code_verifier = "test-verifier"
        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=test-client"
            "&redirect_uri=https://example.com/callback"
            f"&code_challenge={code_verifier}"
            "&code_challenge_method=unknown",  # Unknown method
            follow_redirects=False,
        )
        assert response.status_code == 302

        import urllib.parse

        parsed = urllib.parse.urlparse(response.headers["location"])
        query = urllib.parse.parse_qs(parsed.query)
        code = query["code"][0]

        # Exchange should fail because unknown method returns False
        token_response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": code_verifier,
            },
        )
        assert token_response.status_code == 400

    def test_authorize_with_debug_logging(self):
        """Authorize should work with debug mode enabled."""
        provider = StaticAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
            debug=True,
        )
        routes = provider.get_routes()
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get(
            "/authorize"
            "?client_id=test-client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256"
            "&response_type=code",
            follow_redirects=False,
        )
        assert response.status_code == 302


class TestStaticTokenValidatorDebug:
    """Tests for StaticTokenValidator debug mode."""

    def test_validate_with_debug(self):
        """Validator should work with debug mode enabled."""
        import base64

        validator = StaticTokenValidator(
            client_id="test-client",
            client_secret="test-secret",
            debug=True,
        )
        token = base64.b64encode(b"test-client:test-secret").decode()

        # Run in async context
        import asyncio

        result = asyncio.run(validator.validate_token(token))
        assert result is True

    def test_extract_token_with_debug(self):
        """Token extraction should work with debug mode enabled."""
        from starlette.testclient import TestClient as SyncTestClient

        validator = StaticTokenValidator(
            client_id="test-client",
            client_secret="test-secret",
            debug=True,
        )

        # Create a mock request
        async def app(scope, receive, send):
            request = Request(scope, receive)
            token = validator.extract_token(request)
            response = JSONResponse({"token": token})
            await response(scope, receive, send)

        client = SyncTestClient(app)
        response = client.get("/", headers={"Authorization": "Bearer test-token"})
        assert response.json()["token"] == "test-token"

    def test_extract_token_no_header(self):
        """Token extraction should return None when no auth header."""
        from starlette.testclient import TestClient as SyncTestClient

        validator = StaticTokenValidator(
            client_id="test-client",
            client_secret="test-secret",
        )

        async def app(scope, receive, send):
            request = Request(scope, receive)
            token = validator.extract_token(request)
            response = JSONResponse({"token": token})
            await response(scope, receive, send)

        client = SyncTestClient(app)
        response = client.get("/")  # No Authorization header
        assert response.json()["token"] is None


class TestStaticAuthProviderCIMDFlows:
    """Tests for Client ID Metadata Document (CIMD) flows."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = StaticAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
            debug=True,
        )
        routes = self.provider.get_routes()
        self.app = Starlette(routes=routes)
        self.client = TestClient(self.app)

    @patch("mcp_proxy.auth.fetch_cimd_metadata")
    async def test_authorize_with_cimd_client_id(self, mock_fetch):
        """Authorize should handle CIMD client_id (https URL)."""
        mock_fetch.return_value = CIMDMetadata(
            client_id="https://example.com/client",
            client_name="Test Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=time.time(),
        )

        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=https://example.com/client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256",
            follow_redirects=False,
        )
        assert response.status_code == 302  # Redirect with code

    @patch("mcp_proxy.auth.fetch_cimd_metadata")
    async def test_authorize_cimd_fetch_fails(self, mock_fetch):
        """Authorize should reject when CIMD fetch fails."""
        mock_fetch.return_value = None  # Fetch failed

        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=https://example.com/client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_client"

    @patch("mcp_proxy.auth.fetch_cimd_metadata")
    async def test_authorize_cimd_redirect_uri_mismatch(self, mock_fetch):
        """Authorize should reject when redirect_uri not in CIMD."""
        mock_fetch.return_value = CIMDMetadata(
            client_id="https://example.com/client",
            client_name="Test Client",
            redirect_uris=["https://example.com/other-callback"],  # Different!
            fetched_at=time.time(),
        )

        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=https://example.com/client"
            "&redirect_uri=https://example.com/callback"
            "&code_challenge=test-challenge"
            "&code_challenge_method=S256",
        )
        assert response.status_code == 400
        assert "redirect_uri" in response.json().get("error_description", "")


class TestStaticAuthProviderTokenExchange:
    """Tests for OAuth token exchange flows."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = StaticAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
            debug=True,
        )
        routes = self.provider.get_routes()
        self.app = Starlette(routes=routes)
        self.client = TestClient(self.app)

    def _get_auth_code(self, code_challenge="test-challenge"):
        """Helper to get an authorization code."""
        response = self.client.get(
            "/authorize"
            "?response_type=code"
            "&client_id=test-client"
            f"&redirect_uri=https://example.com/callback"
            f"&code_challenge={code_challenge}"
            "&code_challenge_method=S256",
            follow_redirects=False,
        )
        import urllib.parse

        parsed = urllib.parse.urlparse(response.headers["location"])
        query = urllib.parse.parse_qs(parsed.query)
        return query["code"][0]

    def test_token_exchange_with_debug(self):
        """Token exchange should work with debug logging."""
        code = self._get_auth_code()

        # Try exchange (will fail PKCE but tests debug logging)
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "wrong-verifier",
            },
        )
        # Will fail PKCE but debug logging should be executed
        assert response.status_code == 400

    def test_token_exchange_expired_code(self):
        """Token exchange should reject expired codes."""
        # This is hard to test without time mocking, but we can test other paths
        code = self._get_auth_code()

        # First exchange (should fail PKCE but consume code)
        self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "test",
            },
        )

        # Second exchange should fail - code already consumed or invalid
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "test",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_token_exchange_wrong_redirect_uri(self):
        """Token exchange should reject mismatched redirect_uri."""
        code = self._get_auth_code()

        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://wrong.example.com/callback",  # Wrong!
                "code_verifier": "test",
            },
        )
        assert response.status_code == 400

    def test_refresh_token_grant(self):
        """Token endpoint should support refresh_token grant."""
        # First get a valid token to get a refresh token
        import base64
        import hashlib

        code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )

        code = self._get_auth_code(code_challenge=code_challenge)

        # Exchange for tokens
        token_response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": code_verifier,
            },
        )
        assert token_response.status_code == 200
        refresh_token = token_response.json()["refresh_token"]

        # Now use refresh token
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_token_exchange_successful_pkce(self):
        """Token exchange should succeed with valid PKCE."""
        import base64
        import hashlib

        # Generate proper PKCE challenge
        code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )

        code = self._get_auth_code(code_challenge=code_challenge)

        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert "refresh_token" in data


class TestOAuthProviderBasics:
    """Tests for OAuthProvider class."""

    def test_oauth_provider_creation(self):
        """OAuthProvider should be created with required fields."""
        from mcp_proxy.auth import OAuthProvider

        provider = OAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            token_url="https://auth.example.com/token",
        )
        assert provider.client_id == "test-client"
        assert provider.token_url == "https://auth.example.com/token"

    def test_oauth_provider_get_routes(self):
        """OAuthProvider should return empty routes (external OAuth)."""
        from mcp_proxy.auth import OAuthProvider

        provider = OAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            token_url="https://auth.example.com/token",
        )
        routes = provider.get_routes()
        assert routes == []

    def test_oauth_provider_get_excluded_paths(self):
        """OAuthProvider should return health path excluded."""
        from mcp_proxy.auth import OAuthProvider

        provider = OAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            token_url="https://auth.example.com/token",
        )
        excluded = provider.get_excluded_paths()
        assert "/health" in excluded

    def test_oauth_provider_get_validator(self):
        """OAuthProvider should return OAuthValidator."""
        from mcp_proxy.auth import OAuthProvider, OAuthValidator

        provider = OAuthProvider(
            client_id="test-client",
            client_secret="test-secret",
            token_url="https://auth.example.com/token",
            scopes=["read", "write"],
            audience="https://api.example.com",
        )
        validator = provider.get_validator()
        assert isinstance(validator, OAuthValidator)
        assert validator.scopes == ["read", "write"]
        assert validator.audience == "https://api.example.com"


class TestDeprecatedCreateOAuthRoutes:
    """Tests for deprecated create_oauth_routes function."""

    def test_create_oauth_routes(self):
        """create_oauth_routes should return StaticAuthProvider routes."""
        from mcp_proxy.auth import create_oauth_routes

        routes = create_oauth_routes(
            client_id="test-client",
            client_secret="test-secret",
            issuer_url="https://auth.example.com",
        )
        assert len(routes) > 0
        paths = [r.path for r in routes]
        assert "/.well-known/oauth-authorization-server" in paths


class TestAuthMiddlewareResourceMetadata:
    """Tests for AuthMiddleware with resource metadata URL."""

    def test_middleware_www_authenticate_with_metadata(self):
        """Middleware should include resource_metadata in WWW-Authenticate."""
        from mcp_proxy.auth import AuthMiddleware, StaticTokenValidator

        validator = StaticTokenValidator(client_id="test", client_secret="test")

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        middleware = AuthMiddleware(
            app,
            validator,
            resource_metadata_url="https://example.com/.well-known/oauth-protected-resource",
        )

        assert middleware.resource_metadata_url is not None
        header = middleware._www_authenticate_header()
        assert 'resource_metadata="https://example.com' in header

    def test_middleware_www_authenticate_without_metadata(self):
        """Middleware should return simple Bearer without metadata."""
        from mcp_proxy.auth import AuthMiddleware, StaticTokenValidator

        validator = StaticTokenValidator(client_id="test", client_secret="test")

        async def app(scope, receive, send):
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        middleware = AuthMiddleware(app, validator)
        header = middleware._www_authenticate_header()
        assert header == "Bearer"


class TestFetchCIMDWithDebug:
    """Tests for CIMD fetching with debug mode."""

    async def test_fetch_cimd_non_https_with_debug(self):
        """fetch_cimd_metadata should log rejection of non-HTTPS URLs in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "http://example.com/client", cache, debug=True
        )
        assert result is None

    async def test_fetch_cimd_internal_ip_with_debug(self):
        """fetch_cimd_metadata should log blocking of internal IPs in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "https://192.168.1.1/client", cache, debug=True
        )
        assert result is None

    @patch("httpx.AsyncClient")
    async def test_fetch_cimd_non_200_with_debug(self, mock_client):
        """fetch_cimd_metadata should log non-200 responses in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "https://example.com/client", cache, debug=True
        )
        assert result is None

    @patch("httpx.AsyncClient")
    async def test_fetch_cimd_mismatch_with_debug(self, mock_client):
        """fetch_cimd_metadata should log client_id mismatch in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "https://other.com/client",  # Mismatch!
            "redirect_uris": ["https://example.com/callback"],
        }
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "https://example.com/client", cache, debug=True
        )
        assert result is None

    @patch("httpx.AsyncClient")
    async def test_fetch_cimd_redirect_uris_not_list(self, mock_client):
        """fetch_cimd_metadata should reject non-list redirect_uris."""
        from mcp_proxy.auth import fetch_cimd_metadata

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "https://example.com/client",
            "redirect_uris": "not-a-list",  # Should be a list
        }
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        cache: dict = {}
        result = await fetch_cimd_metadata("https://example.com/client", cache)
        assert result is None

    @patch("httpx.AsyncClient")
    async def test_fetch_cimd_success_with_debug(self, mock_client):
        """fetch_cimd_metadata should log successful fetch in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "https://example.com/client",
            "client_name": "Test Client",
            "redirect_uris": ["https://example.com/callback"],
        }
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "https://example.com/client", cache, debug=True
        )
        assert result is not None
        assert result.client_name == "Test Client"

    @patch("httpx.AsyncClient")
    async def test_fetch_cimd_exception_with_debug(self, mock_client):
        """fetch_cimd_metadata should log exceptions in debug."""
        from mcp_proxy.auth import fetch_cimd_metadata

        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("Network error")
        )

        cache: dict = {}
        result = await fetch_cimd_metadata(
            "https://example.com/client", cache, debug=True
        )
        assert result is None

    async def test_fetch_cimd_url_parse_exception(self):
        """fetch_cimd_metadata should handle URL parsing exceptions."""
        from mcp_proxy.auth import fetch_cimd_metadata

        # This URL has invalid characters that might cause parsing issues
        cache: dict = {}
        # The function catches exceptions during URL parsing
        result = await fetch_cimd_metadata(
            "https://",
            cache,  # Invalid URL
        )
        assert result is None
