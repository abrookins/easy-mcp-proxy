"""Tests for authentication module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestParseTokenConfig:
    """Tests for parse_token_config function."""

    def test_simple_token(self):
        """Simple token string returns auto-generated client_id."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-secret-token")
        assert token == "my-secret-token"
        assert config["client_id"].startswith("static-")
        assert config["scopes"] == []

    def test_token_with_client_id(self):
        """Token with client_id parses correctly."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token:my-client")
        assert token == "my-token"
        assert config["client_id"] == "my-client"
        assert config["scopes"] == []

    def test_token_with_client_id_and_scopes(self):
        """Token with client_id and scopes parses correctly."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token:my-client:read,write")
        assert token == "my-token"
        assert config["client_id"] == "my-client"
        assert config["scopes"] == ["read", "write"]

    def test_token_with_empty_client_id_uses_default(self):
        """Empty client_id falls back to auto-generated."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token::read,write")
        assert token == "my-token"
        assert config["client_id"].startswith("static-")
        assert config["scopes"] == ["read", "write"]

    def test_token_with_whitespace_in_scopes(self):
        """Whitespace in scopes is stripped."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token:client: read , write ")
        assert config["scopes"] == ["read", "write"]

    def test_scopes_with_colons(self):
        """Scopes containing colons (like mcp:tools) parse correctly."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token:admin:mcp:tools")
        assert token == "my-token"
        assert config["client_id"] == "admin"
        assert config["scopes"] == ["mcp:tools"]

    def test_multiple_scopes_with_colons(self):
        """Multiple scopes with colons parse correctly."""
        from mcp_proxy.auth import parse_token_config

        token, config = parse_token_config("my-token:admin:mcp:tools,api:read")
        assert token == "my-token"
        assert config["client_id"] == "admin"
        assert config["scopes"] == ["mcp:tools", "api:read"]


class TestGetStaticTokenConfigs:
    """Tests for get_static_token_configs function."""

    def test_ignores_empty_tokens(self):
        """get_static_token_configs ignores entries with empty tokens."""
        from mcp_proxy.auth import get_static_token_configs

        # Entry with empty token ":client:scope" should be skipped
        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": ":empty-client:read;valid-token:client:write"},
            clear=True,
        ):
            configs = get_static_token_configs()
            # Only the valid token should be present
            assert "valid-token" in configs
            assert "" not in configs
            assert len(configs) == 1


class TestStaticTokenAuth:
    """Tests for static token authentication."""

    def test_get_static_tokens_returns_empty_when_not_set(self):
        """get_static_tokens returns empty list when env var not set."""
        from mcp_proxy.auth import get_static_tokens

        with patch.dict(os.environ, {}, clear=True):
            assert get_static_tokens() == []

    def test_get_static_tokens_parses_semicolon_separated(self):
        """get_static_tokens parses semicolon-separated tokens."""
        from mcp_proxy.auth import get_static_tokens

        with patch.dict(
            os.environ, {"MCP_PROXY_AUTH_TOKENS": "token1;token2;token3"}, clear=True
        ):
            tokens = get_static_tokens()
            assert tokens == ["token1", "token2", "token3"]

    def test_get_static_tokens_strips_whitespace(self):
        """get_static_tokens strips whitespace from tokens."""
        from mcp_proxy.auth import get_static_tokens

        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": " token1 ; token2 ; token3 "},
            clear=True,
        ):
            tokens = get_static_tokens()
            assert tokens == ["token1", "token2", "token3"]

    def test_get_static_tokens_ignores_empty(self):
        """get_static_tokens ignores empty tokens."""
        from mcp_proxy.auth import get_static_tokens

        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": "token1;;token2;  ;token3"},
            clear=True,
        ):
            tokens = get_static_tokens()
            assert tokens == ["token1", "token2", "token3"]

    def test_get_static_tokens_extracts_token_from_extended_format(self):
        """get_static_tokens extracts just token part from extended format."""
        from mcp_proxy.auth import get_static_tokens

        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": "token1:client1:read;token2:client2"},
            clear=True,
        ):
            tokens = get_static_tokens()
            assert tokens == ["token1", "token2"]

    def test_get_static_token_configs_returns_full_config(self):
        """get_static_token_configs returns full token configuration."""
        from mcp_proxy.auth import get_static_token_configs

        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": "admin-key:admin:read,write;reader:reader:read"},
            clear=True,
        ):
            configs = get_static_token_configs()
            assert "admin-key" in configs
            assert configs["admin-key"]["client_id"] == "admin"
            assert configs["admin-key"]["scopes"] == ["read", "write"]
            assert configs["reader"]["client_id"] == "reader"
            assert configs["reader"]["scopes"] == ["read"]

    def test_get_static_token_configs_returns_empty_when_not_set(self):
        """get_static_token_configs returns empty dict when env var not set."""
        from mcp_proxy.auth import get_static_token_configs

        with patch.dict(os.environ, {}, clear=True):
            assert get_static_token_configs() == {}

    def test_is_static_auth_configured_false_when_not_set(self):
        """is_static_auth_configured returns False when not set."""
        from mcp_proxy.auth import is_static_auth_configured

        with patch.dict(os.environ, {}, clear=True):
            assert is_static_auth_configured() is False

    def test_is_static_auth_configured_true_when_set(self):
        """is_static_auth_configured returns True when tokens are set."""
        from mcp_proxy.auth import is_static_auth_configured

        with patch.dict(os.environ, {"MCP_PROXY_AUTH_TOKENS": "my-token"}, clear=True):
            assert is_static_auth_configured() is True

    def test_create_auth_provider_returns_static_verifier(self):
        """create_auth_provider returns StaticTokenVerifier for static tokens."""
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

        from mcp_proxy.auth import create_auth_provider

        with patch.dict(os.environ, {"MCP_PROXY_AUTH_TOKENS": "my-token"}, clear=True):
            result = create_auth_provider()
            assert result is not None
            assert isinstance(result, StaticTokenVerifier)

    @pytest.mark.asyncio
    async def test_static_token_verifier_accepts_valid_token(self):
        """Static token verifier accepts a valid token."""
        from mcp_proxy.auth import create_auth_provider

        with patch.dict(
            os.environ, {"MCP_PROXY_AUTH_TOKENS": "my-secret-token"}, clear=True
        ):
            provider = create_auth_provider()
            result = await provider.verify_token("my-secret-token")
            assert result is not None

    @pytest.mark.asyncio
    async def test_static_token_verifier_rejects_invalid_token(self):
        """Static token verifier rejects an invalid token."""
        from mcp_proxy.auth import create_auth_provider

        with patch.dict(
            os.environ, {"MCP_PROXY_AUTH_TOKENS": "my-secret-token"}, clear=True
        ):
            provider = create_auth_provider()
            result = await provider.verify_token("wrong-token")
            assert result is None


class TestCompositeAuthProvider:
    """Tests for CompositeAuthProvider."""

    @pytest.mark.asyncio
    async def test_composite_tries_static_first(self):
        """CompositeAuthProvider tries static token first."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static.verify_token = AsyncMock(return_value="static-result")
        mock_oidc = MagicMock()
        mock_oidc.verify_token = AsyncMock(return_value="oidc-result")

        composite = CompositeAuthProvider(
            static_provider=mock_static, oidc_provider=mock_oidc
        )
        result = await composite.verify_token("test-token")

        assert result == "static-result"
        mock_static.verify_token.assert_called_once_with("test-token")
        mock_oidc.verify_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_composite_falls_back_to_oidc(self):
        """CompositeAuthProvider falls back to OIDC if static fails."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static.verify_token = AsyncMock(return_value=None)
        mock_oidc = MagicMock()
        mock_oidc.verify_token = AsyncMock(return_value="oidc-result")

        composite = CompositeAuthProvider(
            static_provider=mock_static, oidc_provider=mock_oidc
        )
        result = await composite.verify_token("test-token")

        assert result == "oidc-result"
        mock_static.verify_token.assert_called_once()
        mock_oidc.verify_token.assert_called_once_with("test-token")

    @pytest.mark.asyncio
    async def test_composite_returns_none_if_both_fail(self):
        """CompositeAuthProvider returns None if both providers fail."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static.verify_token = AsyncMock(return_value=None)
        mock_oidc = MagicMock()
        mock_oidc.verify_token = AsyncMock(return_value=None)

        composite = CompositeAuthProvider(
            static_provider=mock_static, oidc_provider=mock_oidc
        )
        result = await composite.verify_token("test-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_composite_works_with_only_static(self):
        """CompositeAuthProvider works with only static provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static.verify_token = AsyncMock(return_value="static-result")

        composite = CompositeAuthProvider(static_provider=mock_static)
        result = await composite.verify_token("test-token")

        assert result == "static-result"

    @pytest.mark.asyncio
    async def test_composite_works_with_only_oidc(self):
        """CompositeAuthProvider works with only OIDC provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_oidc.verify_token = AsyncMock(return_value="oidc-result")

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = await composite.verify_token("test-token")

        assert result == "oidc-result"

    def test_composite_get_routes_delegates_to_oidc(self):
        """CompositeAuthProvider.get_routes delegates to OIDC provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_oidc.get_routes = MagicMock(return_value=["route1", "route2"])

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = composite.get_routes("/mcp")

        assert result == ["route1", "route2"]
        mock_oidc.get_routes.assert_called_once_with("/mcp")

    def test_composite_get_routes_returns_empty_without_oidc(self):
        """CompositeAuthProvider.get_routes returns [] without OIDC."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        composite = CompositeAuthProvider(static_provider=mock_static)
        result = composite.get_routes("/mcp")

        assert result == []

    def test_composite_get_well_known_routes_delegates_to_oidc(self):
        """CompositeAuthProvider.get_well_known_routes delegates to OIDC."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_oidc.get_well_known_routes = MagicMock(return_value=["wk1", "wk2"])

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = composite.get_well_known_routes("/mcp")

        assert result == ["wk1", "wk2"]

    def test_composite_get_middleware_returns_middleware_with_composite_verifier(self):
        """get_middleware returns middleware using composite for verification."""
        from starlette.middleware import Middleware

        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_static = MagicMock()

        composite = CompositeAuthProvider(
            oidc_provider=mock_oidc, static_provider=mock_static
        )
        result = composite.get_middleware()

        # Should return exactly 2 middleware items
        assert len(result) == 2
        # Both should be Starlette Middleware instances
        assert all(isinstance(m, Middleware) for m in result)

    @pytest.mark.asyncio
    async def test_composite_returns_none_with_no_providers(self):
        """CompositeAuthProvider returns None when no providers configured."""
        from mcp_proxy.auth import CompositeAuthProvider

        composite = CompositeAuthProvider()
        result = await composite.verify_token("test-token")

        assert result is None

    def test_composite_get_well_known_routes_returns_empty_without_oidc(self):
        """CompositeAuthProvider.get_well_known_routes returns [] without OIDC."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        composite = CompositeAuthProvider(static_provider=mock_static)
        result = composite.get_well_known_routes("/mcp")

        assert result == []

    def test_composite_get_middleware_works_without_oidc(self):
        """CompositeAuthProvider.get_middleware works with only static provider."""
        from starlette.middleware import Middleware

        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        composite = CompositeAuthProvider(static_provider=mock_static)
        result = composite.get_middleware()

        # Should still return middleware that uses composite for verification
        assert len(result) == 2
        assert all(isinstance(m, Middleware) for m in result)

    def test_composite_required_scopes_always_empty(self):
        """required_scopes always returns [] for per-provider enforcement."""
        from mcp_proxy.auth import CompositeAuthProvider

        # Even with OIDC provider that has scopes, composite returns []
        mock_oidc = MagicMock()
        mock_oidc.required_scopes = ["read", "write"]
        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        assert composite.required_scopes == []

        # With static provider that has scopes, still returns []
        mock_static = MagicMock()
        mock_static.required_scopes = ["admin"]
        composite = CompositeAuthProvider(static_provider=mock_static)
        assert composite.required_scopes == []

        # With both providers, still returns []
        composite = CompositeAuthProvider(
            oidc_provider=mock_oidc, static_provider=mock_static
        )
        assert composite.required_scopes == []

        # Without providers, returns []
        composite = CompositeAuthProvider()
        assert composite.required_scopes == []

    def test_composite_base_url_from_oidc(self):
        """CompositeAuthProvider.base_url delegates to OIDC provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_oidc.base_url = "http://localhost:8000"

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        assert composite.base_url == "http://localhost:8000"

    def test_composite_base_url_from_static(self):
        """CompositeAuthProvider.base_url falls back to static provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static.base_url = "http://localhost:9000"

        composite = CompositeAuthProvider(static_provider=mock_static)
        assert composite.base_url == "http://localhost:9000"

    def test_composite_base_url_none_without_providers(self):
        """CompositeAuthProvider.base_url returns None without providers."""
        from mcp_proxy.auth import CompositeAuthProvider

        composite = CompositeAuthProvider()
        assert composite.base_url is None

    def test_composite_get_resource_url_delegates_to_oidc(self):
        """CompositeAuthProvider._get_resource_url delegates to OIDC provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock()
        mock_oidc._get_resource_url = MagicMock(
            return_value="http://localhost:8000/mcp"
        )

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = composite._get_resource_url("/mcp")

        assert result == "http://localhost:8000/mcp"
        mock_oidc._get_resource_url.assert_called_once_with("/mcp")

    def test_composite_get_resource_url_delegates_to_static(self):
        """CompositeAuthProvider._get_resource_url falls back to static provider."""
        from mcp_proxy.auth import CompositeAuthProvider

        mock_static = MagicMock()
        mock_static._get_resource_url = MagicMock(
            return_value="http://localhost:9000/mcp"
        )

        composite = CompositeAuthProvider(static_provider=mock_static)
        result = composite._get_resource_url("/mcp")

        assert result == "http://localhost:9000/mcp"
        mock_static._get_resource_url.assert_called_once_with("/mcp")

    def test_composite_get_resource_url_constructs_from_base_url(self):
        """CompositeAuthProvider._get_resource_url constructs URL from base_url."""
        from pydantic import AnyHttpUrl

        from mcp_proxy.auth import CompositeAuthProvider

        # Provider with base_url but no _get_resource_url method
        mock_oidc = MagicMock(spec=["base_url"])
        mock_oidc.base_url = AnyHttpUrl("http://localhost:8000")

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = composite._get_resource_url("/mcp")

        assert str(result) == "http://localhost:8000/mcp"

    def test_composite_get_resource_url_returns_none_without_base_url(self):
        """CompositeAuthProvider._get_resource_url returns None without base_url."""
        from mcp_proxy.auth import CompositeAuthProvider

        composite = CompositeAuthProvider()
        result = composite._get_resource_url("/mcp")

        assert result is None

    def test_composite_get_resource_url_returns_base_url_without_path(self):
        """CompositeAuthProvider._get_resource_url returns base_url when no path."""
        from pydantic import AnyHttpUrl

        from mcp_proxy.auth import CompositeAuthProvider

        mock_oidc = MagicMock(spec=["base_url"])
        mock_oidc.base_url = AnyHttpUrl("http://localhost:8000")

        composite = CompositeAuthProvider(oidc_provider=mock_oidc)
        result = composite._get_resource_url(None)

        assert str(result) == "http://localhost:8000/"


class TestCreateAuthProviderModes:
    """Tests for different auth provider modes."""

    def test_returns_composite_when_both_configured(self):
        """create_auth_provider returns CompositeAuthProvider for both."""
        from mcp_proxy.auth import CompositeAuthProvider, create_auth_provider

        mock_oidc_config = {
            "issuer": "https://test.auth0.com/",
            "authorization_endpoint": "https://test.auth0.com/authorize",
            "token_endpoint": "https://test.auth0.com/oauth/token",
            "userinfo_endpoint": "https://test.auth0.com/userinfo",
            "jwks_uri": "https://test.auth0.com/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with patch.dict(
            os.environ,
            {
                "MCP_PROXY_AUTH_TOKENS": "my-token",
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET": "test-client-secret",
                "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE": "https://api.test.com",
                "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL": "http://localhost:8000",
            },
            clear=True,
        ):
            with patch("httpx.get") as mock_get:
                mock_response = mock_get.return_value
                mock_response.status_code = 200
                mock_response.json.return_value = mock_oidc_config

                result = create_auth_provider()
                assert result is not None
                assert isinstance(result, CompositeAuthProvider)
                assert result.static_provider is not None
                assert result.oidc_provider is not None


class TestCreateAuthProvider:
    """Tests for create_auth_provider function."""

    def test_returns_none_when_no_env_vars(self):
        """create_auth_provider returns None when env vars are not set."""
        from mcp_proxy.auth import create_auth_provider

        with patch.dict(os.environ, {}, clear=True):
            result = create_auth_provider()
            assert result is None

    def test_returns_none_when_partial_env_vars(self):
        """create_auth_provider returns None when only some env vars are set."""
        from mcp_proxy.auth import create_auth_provider

        # Only set some of the required vars
        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                # Missing: CLIENT_SECRET, AUDIENCE, BASE_URL
            },
            clear=True,
        ):
            result = create_auth_provider()
            assert result is None

    def test_returns_provider_when_all_env_vars_set(self):
        """create_auth_provider returns OIDCProxy when all env vars are set."""
        from mcp_proxy.auth import create_auth_provider

        # Mock the OIDC configuration fetch since OIDCProxy fetches it on init
        mock_oidc_config = {
            "issuer": "https://test.auth0.com/",
            "authorization_endpoint": "https://test.auth0.com/authorize",
            "token_endpoint": "https://test.auth0.com/oauth/token",
            "userinfo_endpoint": "https://test.auth0.com/userinfo",
            "jwks_uri": "https://test.auth0.com/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET": "test-client-secret",
                "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE": "https://api.test.com",
                "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL": "http://localhost:8000",
            },
            clear=True,
        ):
            with patch("httpx.get") as mock_get:
                mock_response = mock_get.return_value
                mock_response.status_code = 200
                mock_response.json.return_value = mock_oidc_config

                result = create_auth_provider()
                assert result is not None
                # Verify it's an OIDCProxy (we use this instead of Auth0Provider
                # to work around FastMCP's default scope behavior)
                from fastmcp.server.auth.oidc_proxy import OIDCProxy

                assert isinstance(result, OIDCProxy)

    def test_parses_required_scopes_from_env(self):
        """create_auth_provider parses required_scopes from env var."""
        from mcp_proxy.auth import create_auth_provider

        mock_oidc_config = {
            "issuer": "https://test.auth0.com/",
            "authorization_endpoint": "https://test.auth0.com/authorize",
            "token_endpoint": "https://test.auth0.com/oauth/token",
            "userinfo_endpoint": "https://test.auth0.com/userinfo",
            "jwks_uri": "https://test.auth0.com/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET": "test-client-secret",
                "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE": "https://api.test.com",
                "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL": "http://localhost:8000",
                "FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES": "read:tools, write:tools",
            },
            clear=True,
        ):
            with patch("httpx.get") as mock_get:
                mock_response = mock_get.return_value
                mock_response.status_code = 200
                mock_response.json.return_value = mock_oidc_config

                result = create_auth_provider()
                assert result is not None
                # Verify required_scopes was parsed correctly
                assert result.required_scopes == ["read:tools", "write:tools"]


class TestIsAuthConfigured:
    """Tests for is_auth_configured function."""

    def test_returns_false_when_no_env_vars(self):
        """is_auth_configured returns False when env vars are not set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(os.environ, {}, clear=True):
            assert is_auth_configured() is False

    def test_returns_false_when_partial_oidc_env_vars(self):
        """is_auth_configured returns False when only some OIDC env vars are set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
            },
            clear=True,
        ):
            assert is_auth_configured() is False

    def test_returns_true_when_oidc_env_vars_set(self):
        """is_auth_configured returns True when all OIDC env vars are set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET": "test-client-secret",
                "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE": "https://api.test.com",
                "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL": "http://localhost:8000",
            },
            clear=True,
        ):
            assert is_auth_configured() is True

    def test_returns_true_when_static_tokens_set(self):
        """is_auth_configured returns True when static tokens are set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(
            os.environ,
            {"MCP_PROXY_AUTH_TOKENS": "my-token"},
            clear=True,
        ):
            assert is_auth_configured() is True


class TestIsOidcAuthConfigured:
    """Tests for is_oidc_auth_configured function."""

    def test_returns_false_when_no_env_vars(self):
        """is_oidc_auth_configured returns False when env vars are not set."""
        from mcp_proxy.auth import is_oidc_auth_configured

        with patch.dict(os.environ, {}, clear=True):
            assert is_oidc_auth_configured() is False

    def test_returns_true_when_all_env_vars_set(self):
        """is_oidc_auth_configured returns True when all env vars are set."""
        from mcp_proxy.auth import is_oidc_auth_configured

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID": "test-client-id",
                "FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET": "test-client-secret",
                "FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE": "https://api.test.com",
                "FASTMCP_SERVER_AUTH_AUTH0_BASE_URL": "http://localhost:8000",
            },
            clear=True,
        ):
            assert is_oidc_auth_configured() is True
