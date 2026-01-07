"""Tests for authentication module."""

import os
from unittest.mock import patch


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
        """create_auth_provider returns Auth0Provider when all env vars are set."""
        from mcp_proxy.auth import create_auth_provider

        # Mock the OIDC configuration fetch since Auth0Provider tries to fetch it
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
                # Verify it's an Auth0Provider
                from fastmcp.server.auth.providers.auth0 import Auth0Provider

                assert isinstance(result, Auth0Provider)


class TestIsAuthConfigured:
    """Tests for is_auth_configured function."""

    def test_returns_false_when_no_env_vars(self):
        """is_auth_configured returns False when env vars are not set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(os.environ, {}, clear=True):
            assert is_auth_configured() is False

    def test_returns_false_when_partial_env_vars(self):
        """is_auth_configured returns False when only some env vars are set."""
        from mcp_proxy.auth import is_auth_configured

        with patch.dict(
            os.environ,
            {
                "FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL": "https://test.auth0.com/.well-known/openid-configuration",
            },
            clear=True,
        ):
            assert is_auth_configured() is False

    def test_returns_true_when_all_env_vars_set(self):
        """is_auth_configured returns True when all env vars are set."""
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
