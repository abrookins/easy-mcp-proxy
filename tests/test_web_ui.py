"""Tests for web UI functionality."""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from starlette.testclient import TestClient

from mcp_proxy.web_ui import (
    SESSION_COOKIE_NAME,
    _build_html_template,
    _build_restart_html,
    _exchange_code_for_token,
    _get_oauth_client_id,
    _get_oidc_provider,
    _get_session_secret,
    _get_token_url,
    _sign_session_data,
    _verify_session_data,
    create_session_cookie,
    create_web_ui_routes,
    get_authorization_url,
    get_config_path,
    get_overrides_path,
    is_browser_request,
    load_overrides,
    load_raw_config,
    merge_config,
    render_servers_html,
    render_views_html,
    save_overrides,
    verify_session_cookie,
)


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_config_path_default(self, monkeypatch):
        """get_config_path should return default when env not set."""
        monkeypatch.delenv("MCP_PROXY_CONFIG", raising=False)
        path = get_config_path()
        assert path == Path("config.yaml")

    def test_get_config_path_from_env(self, monkeypatch):
        """get_config_path should use MCP_PROXY_CONFIG env var."""
        monkeypatch.setenv("MCP_PROXY_CONFIG", "/custom/path.yaml")
        path = get_config_path()
        assert path == Path("/custom/path.yaml")

    def test_get_overrides_path(self, tmp_path):
        """get_overrides_path should return .overrides.json suffix."""
        config_path = tmp_path / "config.yaml"
        result = get_overrides_path(config_path)
        assert result == tmp_path / "config.overrides.json"

    def test_load_raw_config_nonexistent(self, tmp_path):
        """load_raw_config should return empty config when file missing."""
        config_path = tmp_path / "nonexistent.yaml"
        result = load_raw_config(config_path)
        assert result == {"mcp_servers": {}, "tool_views": {}}

    def test_load_raw_config_existing(self, tmp_path):
        """load_raw_config should load YAML content."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {"s1": {}}}))
        result = load_raw_config(config_path)
        assert "s1" in result["mcp_servers"]

    def test_load_overrides_nonexistent(self, tmp_path):
        """load_overrides should return empty dict when file missing."""
        config_path = tmp_path / "config.yaml"
        result = load_overrides(config_path)
        assert result == {}

    def test_save_and_load_overrides(self, tmp_path):
        """save_overrides and load_overrides should roundtrip."""
        config_path = tmp_path / "config.yaml"
        data = {"key": "value", "nested": {"a": 1}}
        save_overrides(config_path, data)
        result = load_overrides(config_path)
        assert result == data

    def test_merge_config_simple(self):
        """merge_config should combine base and overrides."""
        base = {"a": 1, "b": 2}
        overrides = {"b": 3, "c": 4}
        result = merge_config(base, overrides)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_config_nested(self):
        """merge_config should recursively merge dicts."""
        base = {"nested": {"x": 1, "y": 2}}
        overrides = {"nested": {"y": 10}}
        result = merge_config(base, overrides)
        assert result == {"nested": {"x": 1, "y": 10}}


class TestSessionManagement:
    """Tests for session cookie management."""

    def test_get_session_secret_with_env(self, monkeypatch):
        """_get_session_secret should use AUTH0_CLIENT_SECRET_VAR if available."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")
        secret = _get_session_secret()
        assert secret == "test-secret"

    def test_get_session_secret_generates_fallback(self, monkeypatch):
        """_get_session_secret should generate secret when env not set."""
        monkeypatch.delenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", raising=False)
        secret = _get_session_secret()
        assert len(secret) == 64  # 32 bytes = 64 hex chars

    def test_sign_and_verify_session_data(self, monkeypatch):
        """_sign_session_data and _verify_session_data should roundtrip."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        data = '{"user": "test"}'
        signed = _sign_session_data(data)
        assert "." in signed
        verified = _verify_session_data(signed)
        assert verified == data

    def test_verify_session_data_invalid(self, monkeypatch):
        """_verify_session_data should reject invalid signatures."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        result = _verify_session_data("no-dot-here")
        assert result is None

    def test_verify_session_data_tampered(self, monkeypatch):
        """_verify_session_data should reject tampered data."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        signed = _sign_session_data('{"user": "test"}')
        tampered = "tampered" + signed[8:]
        result = _verify_session_data(tampered)
        assert result is None

    def test_create_session_cookie(self, monkeypatch):
        """create_session_cookie should create a signed cookie value."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        cookie = create_session_cookie("user123")
        assert "." in cookie
        # Verify the cookie can be validated
        session = verify_session_cookie(cookie)
        assert session is not None
        assert session["user_id"] == "user123"

    def test_verify_session_cookie_expired(self, monkeypatch):
        """verify_session_cookie should reject expired sessions."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        # Manually create an expired session
        import json

        expires = int(time.time()) - 100  # 100 seconds ago
        data = json.dumps({"user_id": "test", "expires": expires})
        signed = _sign_session_data(data)
        result = verify_session_cookie(signed)
        assert result is None

    def test_verify_session_cookie_invalid_json(self, monkeypatch):
        """verify_session_cookie should reject invalid JSON."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        signed = _sign_session_data("not-json")
        result = verify_session_cookie(signed)
        assert result is None

    def test_verify_session_cookie_invalid_signature(self, monkeypatch):
        """verify_session_cookie should reject invalid signature."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")
        # Call verify_session_cookie with bad signature to hit line 305
        result = verify_session_cookie("no-dot-here")
        assert result is None

    def test_is_browser_request_with_html_accept(self):
        """is_browser_request should return True for text/html Accept."""
        request = MagicMock()
        request.headers.get.return_value = "text/html,application/xhtml+xml"
        assert is_browser_request(request) is True

    def test_is_browser_request_with_json_accept(self):
        """is_browser_request should return False for JSON Accept."""
        request = MagicMock()
        request.headers.get.return_value = "application/json"
        assert is_browser_request(request) is False

    def test_is_browser_request_no_accept(self):
        """is_browser_request should return False when no Accept header."""
        request = MagicMock()
        request.headers.get.return_value = ""
        assert is_browser_request(request) is False


class TestOAuthHelpers:
    """Tests for OAuth helper functions."""

    def test_get_authorization_url_none_provider(self):
        """get_authorization_url should return None for None provider."""
        result = get_authorization_url(None)
        assert result is None

    def test_get_authorization_url_with_base_url(self):
        """get_authorization_url should construct URL from base_url."""
        # Use spec=[] so oidc_provider attr check returns False (hasattr)
        provider = MagicMock(spec=["base_url"])
        provider.base_url = "https://auth.example.com"
        result = get_authorization_url(provider)
        assert result == "https://auth.example.com/authorize"

    def test_get_authorization_url_composite_provider(self):
        """get_authorization_url should extract OIDC provider from composite."""
        oidc = MagicMock()
        oidc.base_url = "https://oidc.example.com"
        composite = MagicMock()
        composite.oidc_provider = oidc
        result = get_authorization_url(composite)
        assert result == "https://oidc.example.com/authorize"

    def test_get_authorization_url_composite_no_oidc(self):
        """get_authorization_url should return None if OIDC is None."""
        composite = MagicMock()
        composite.oidc_provider = None
        result = get_authorization_url(composite)
        assert result is None

    def test_get_authorization_url_no_base_url(self):
        """get_authorization_url should return None if no base_url."""
        provider = MagicMock(spec=[])  # No base_url attribute
        result = get_authorization_url(provider)
        assert result is None

    def test_get_oidc_provider_none(self):
        """_get_oidc_provider should return None for None provider."""
        result = _get_oidc_provider(None)
        assert result is None

    def test_get_oidc_provider_direct(self):
        """_get_oidc_provider should return provider if no oidc_provider attr."""
        provider = MagicMock(spec=[])
        result = _get_oidc_provider(provider)
        assert result is provider

    def test_get_oidc_provider_composite(self):
        """_get_oidc_provider should return oidc_provider from composite."""
        oidc = MagicMock()
        composite = MagicMock()
        composite.oidc_provider = oidc
        result = _get_oidc_provider(composite)
        assert result is oidc

    def test_get_oauth_client_id_from_provider(self):
        """_get_oauth_client_id should get client_id from provider."""
        # Use spec to control which attrs exist
        provider = MagicMock(spec=["client_id"])
        provider.client_id = "provider-client-id"
        result = _get_oauth_client_id(provider)
        assert result == "provider-client-id"

    def test_get_oauth_client_id_from_env(self, monkeypatch):
        """_get_oauth_client_id should fall back to env var."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID", "env-client-id")
        provider = MagicMock(spec=[])  # No client_id attr
        result = _get_oauth_client_id(provider)
        assert result == "env-client-id"

    def test_get_oauth_client_id_none_provider(self, monkeypatch):
        """_get_oauth_client_id should use env var when provider is None."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID", "env-client")
        result = _get_oauth_client_id(None)
        assert result == "env-client"

    def test_get_token_url_none_provider(self):
        """_get_token_url should return None for None provider."""
        result = _get_token_url(None)
        assert result is None

    def test_get_token_url_from_upstream_endpoint(self):
        """_get_token_url should use upstream_token_endpoint if available."""
        # Use spec to control which attrs exist
        provider = MagicMock(spec=["upstream_token_endpoint"])
        provider.upstream_token_endpoint = "https://auth.example.com/token"
        result = _get_token_url(provider)
        assert result == "https://auth.example.com/token"

    def test_get_token_url_from_base_url(self):
        """_get_token_url should construct from base_url as fallback."""
        provider = MagicMock(spec=["base_url"])
        provider.base_url = "https://auth.example.com"
        result = _get_token_url(provider)
        assert result == "https://auth.example.com/oauth/token"

    def test_get_token_url_no_urls(self):
        """_get_token_url should return None when no URLs available."""
        provider = MagicMock(spec=[])
        result = _get_token_url(provider)
        assert result is None


class TestTokenExchange:
    """Tests for OAuth token exchange."""

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_no_provider(self):
        """_exchange_code_for_token returns None without provider."""
        result = await _exchange_code_for_token(None, "code", "uri")
        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self, monkeypatch):
        """_exchange_code_for_token should exchange code for token."""
        provider = MagicMock()
        provider.upstream_token_endpoint = "https://auth.example.com/token"
        provider.client_id = "test-client"
        provider.client_secret = "test-secret"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "token123", "sub": "user1"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _exchange_code_for_token(
                provider, "auth-code", "https://callback"
            )
        assert result == {"access_token": "token123", "sub": "user1"}

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_failure(self, monkeypatch):
        """_exchange_code_for_token should return None on failure."""
        provider = MagicMock()
        provider.upstream_token_endpoint = "https://auth.example.com/token"
        provider.client_id = "test-client"
        provider.client_secret = "test-secret"

        mock_response = MagicMock()
        mock_response.status_code = 400

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _exchange_code_for_token(
                provider, "bad-code", "https://callback"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_exception(self, monkeypatch):
        """_exchange_code_for_token should return None on exception."""
        provider = MagicMock()
        provider.upstream_token_endpoint = "https://auth.example.com/token"
        provider.client_id = "test-client"
        provider.client_secret = "test-secret"

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Network error")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _exchange_code_for_token(
                provider, "code", "https://callback"
            )
        assert result is None


class TestRenderFunctions:
    """Tests for HTML rendering functions."""

    def test_render_servers_html_empty(self):
        """render_servers_html should handle empty servers."""
        result = render_servers_html({})
        assert "No servers configured" in result

    def test_render_servers_html_stdio(self):
        """render_servers_html should render stdio servers."""
        servers = {"my-server": {"command": "python", "args": ["-m", "server"]}}
        result = render_servers_html(servers)
        assert "my-server" in result
        assert "stdio" in result
        assert "python" in result

    def test_render_servers_html_http(self):
        """render_servers_html should render HTTP servers."""
        servers = {"api": {"url": "https://api.example.com"}}
        result = render_servers_html(servers)
        assert "api" in result
        assert "HTTP" in result
        assert "https://api.example.com" in result

    def test_render_views_html_empty(self):
        """render_views_html should handle empty views."""
        result = render_views_html({})
        assert "No views configured" in result

    def test_render_views_html_with_views(self):
        """render_views_html should render view details."""
        views = {"my-view": {"description": "Test view", "exposure_mode": "search"}}
        result = render_views_html(views)
        assert "my-view" in result
        assert "Test view" in result
        assert "search" in result


class TestHtmlTemplates:
    """Tests for HTML template building."""

    def test_build_html_template(self):
        """_build_html_template should produce valid HTML."""
        html = _build_html_template(
            alert="",
            servers_html="<p>Servers</p>",
            views_html="<p>Views</p>",
            config_yaml="key: value",
            save_url="/save",
            restart_url="/restart",
        )
        assert "<!DOCTYPE html>" in html
        assert "MCP Proxy Configuration" in html
        assert "<p>Servers</p>" in html
        assert "key: value" in html

    def test_build_restart_html(self):
        """_build_restart_html should produce restart page."""
        html = _build_restart_html("/config")
        assert "Restarting" in html
        assert "/config" in html


class TestWebUIRoutes:
    """Tests for web UI routes."""

    @pytest.fixture
    def app_with_routes(self, tmp_path, monkeypatch):
        """Create a Starlette app with web UI routes."""
        from starlette.applications import Starlette

        # Set up config file
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "mcp_servers": {"test": {"command": "echo"}},
                    "tool_views": {"default": {"description": "Test"}},
                }
            )
        )
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        return Starlette(routes=routes)

    def test_config_ui_get(self, app_with_routes):
        """GET /config should return HTML page."""
        client = TestClient(app_with_routes)
        response = client.get("/config")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "MCP Proxy Configuration" in response.text

    def test_config_ui_shows_servers(self, app_with_routes):
        """Config UI should show configured servers."""
        client = TestClient(app_with_routes)
        response = client.get("/config")
        assert "test" in response.text
        assert "echo" in response.text

    def test_config_api_get(self, app_with_routes):
        """GET /config/api should return JSON config."""
        client = TestClient(app_with_routes)
        response = client.get("/config/api")
        assert response.status_code == 200
        data = response.json()
        assert "mcp_servers" in data
        assert "test" in data["mcp_servers"]

    def test_config_api_put(self, app_with_routes, tmp_path, monkeypatch):
        """PUT /config/api should save config as overrides."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        client = TestClient(app_with_routes)
        new_config = {"mcp_servers": {"new": {"url": "https://new.com"}}}
        response = client.put("/config/api", json=new_config)
        assert response.status_code == 200
        assert response.json()["status"] == "saved"

        # Verify overrides were saved
        overrides = load_overrides(config_path)
        assert "new" in overrides["mcp_servers"]

    def test_config_save_post(self, tmp_path, monkeypatch):
        """POST /config/save should save YAML and redirect."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, follow_redirects=False)

        new_yaml = yaml.dump({"mcp_servers": {"s1": {"command": "test"}}})
        response = client.post(
            "/config/save",
            data={"config_yaml": new_yaml},
        )
        assert response.status_code == 303
        assert "saved=1" in response.headers["location"]

    def test_config_save_invalid_yaml(self, tmp_path, monkeypatch):
        """POST /config/save with invalid YAML should show error."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, follow_redirects=False)

        response = client.post(
            "/config/save",
            data={"config_yaml": "not a dict"},
        )
        assert response.status_code == 303
        assert "error=" in response.headers["location"]

    def test_config_ui_with_auth(self, tmp_path, monkeypatch):
        """Config UI should check auth when auth function provided."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        async def deny_all(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        routes = create_web_ui_routes(path_prefix="/config", check_auth=deny_all)
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/config")
        assert response.status_code == 401

    def test_config_ui_saved_alert(self, app_with_routes):
        """Config UI should show success alert after save."""
        client = TestClient(app_with_routes)
        response = client.get("/config?saved=1")
        assert "success" in response.text
        assert "saved successfully" in response.text.lower()

    def test_config_ui_error_alert(self, app_with_routes):
        """Config UI should show error alert."""
        client = TestClient(app_with_routes)
        response = client.get("/config?error=Test+error")
        assert "error" in response.text.lower()
        assert "Test error" in response.text


class TestRestartEndpoint:
    """Tests for restart endpoint."""

    def test_restart_api_json(self, tmp_path, monkeypatch):
        """Restart with Accept: application/json should return JSON."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("os.kill") as mock_kill:
            response = client.get(
                "/config/restart",
                headers={"Accept": "application/json"},
            )
            # Signal will be sent
            assert mock_kill.called
            assert response.status_code == 200
            assert response.json()["status"] == "restart_initiated"

    def test_restart_browser(self, tmp_path, monkeypatch):
        """Restart from browser should return HTML page."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("os.kill") as mock_kill:
            response = client.get("/config/restart")
            assert mock_kill.called
            assert response.status_code == 200
            assert "Restarting" in response.text

    def test_restart_writes_marker(self, tmp_path, monkeypatch):
        """Restart should write marker file."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("os.kill"):
            client.get("/config/restart")

        marker_path = tmp_path / ".mcp-proxy-restart"
        assert marker_path.exists()
        assert marker_path.read_text() == "restart"

    def test_restart_with_auth_denied(self, tmp_path, monkeypatch):
        """Restart should check auth and deny if needed."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        async def deny_all(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        routes = create_web_ui_routes(path_prefix="/config", check_auth=deny_all)
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.get("/config/restart")
        assert response.status_code == 401

    def test_restart_signal_error_api(self, tmp_path, monkeypatch):
        """Restart should handle signal error for API calls."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False)

        with patch("os.kill", side_effect=OSError("signal failed")):
            response = client.get(
                "/config/restart",
                headers={"Accept": "application/json"},
            )
            assert response.status_code == 500
            assert "error" in response.json()

    def test_restart_signal_error_browser(self, tmp_path, monkeypatch):
        """Restart should handle signal error for browser calls."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)

        with patch("os.kill", side_effect=OSError("signal failed")):
            response = client.get("/config/restart")
            assert response.status_code == 303
            assert "error=" in response.headers["location"]


class TestAuthOnEndpoints:
    """Tests for auth checks on all endpoints."""

    @pytest.fixture
    def app_with_auth(self, tmp_path, monkeypatch):
        """Create app with auth that denies all requests."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        async def deny_all(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        routes = create_web_ui_routes(path_prefix="/config", check_auth=deny_all)
        return Starlette(routes=routes)

    def test_save_config_auth_denied(self, app_with_auth):
        """POST /config/save should check auth."""
        client = TestClient(app_with_auth)
        response = client.post(
            "/config/save",
            data={"config_yaml": "key: value"},
        )
        assert response.status_code == 401

    def test_get_config_json_auth_denied(self, app_with_auth):
        """GET /config/api should check auth."""
        client = TestClient(app_with_auth)
        response = client.get("/config/api")
        assert response.status_code == 401

    def test_update_config_json_auth_denied(self, app_with_auth):
        """PUT /config/api should check auth."""
        client = TestClient(app_with_auth)
        response = client.put("/config/api", json={"key": "value"})
        assert response.status_code == 401

    def test_update_config_json_invalid_body(self, tmp_path, monkeypatch):
        """PUT /config/api with invalid JSON should return 400."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app)

        response = client.put(
            "/config/api",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert "error" in response.json()


class TestRestartMarkerWrite:
    """Tests for restart marker file writing."""

    def test_restart_marker_write_error_ignored(self, tmp_path, monkeypatch):
        """Restart should continue even if marker file write fails."""
        from starlette.applications import Starlette

        # Create config in a read-only directory to cause write failure
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        routes = create_web_ui_routes(path_prefix="/config", check_auth=None)
        app = Starlette(routes=routes)
        client = TestClient(app, raise_server_exceptions=False)

        # Mock the marker write to fail
        with patch("os.kill") as mock_kill:
            with patch.object(
                Path, "write_text", side_effect=PermissionError("denied")
            ):
                response = client.get(
                    "/config/restart",
                    headers={"Accept": "application/json"},
                )
                # Should still succeed despite marker write failure
                assert mock_kill.called
                assert response.status_code == 200
                assert response.json()["status"] == "restart_initiated"


class TestAuthAllowsAccess:
    """Tests for auth allowing access (returning None)."""

    @pytest.fixture
    def app_with_auth_allows(self, tmp_path, monkeypatch):
        """Create app with auth that allows all requests."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        async def allow_all(request):
            return None  # No error means allowed

        routes = create_web_ui_routes(path_prefix="/config", check_auth=allow_all)
        return Starlette(routes=routes)

    def test_config_ui_auth_allows(self, app_with_auth_allows):
        """Config UI should work when auth allows."""
        client = TestClient(app_with_auth_allows)
        response = client.get("/config")
        assert response.status_code == 200

    def test_save_config_auth_allows(self, app_with_auth_allows):
        """Save should work when auth allows."""
        client = TestClient(app_with_auth_allows, follow_redirects=False)
        response = client.post(
            "/config/save",
            data={"config_yaml": yaml.dump({"mcp_servers": {}})},
        )
        assert response.status_code == 303

    def test_restart_auth_allows(self, app_with_auth_allows):
        """Restart should work when auth allows."""
        client = TestClient(app_with_auth_allows, raise_server_exceptions=False)
        with patch("os.kill"):
            response = client.get(
                "/config/restart",
                headers={"Accept": "application/json"},
            )
            assert response.status_code == 200

    def test_get_config_json_auth_allows(self, app_with_auth_allows):
        """GET /config/api should work when auth allows."""
        client = TestClient(app_with_auth_allows)
        response = client.get("/config/api")
        assert response.status_code == 200

    def test_update_config_json_auth_allows(self, app_with_auth_allows):
        """PUT /config/api should work when auth allows."""
        client = TestClient(app_with_auth_allows)
        response = client.put("/config/api", json={"mcp_servers": {}})
        assert response.status_code == 200


class TestOAuthRoutes:
    """Tests for OAuth login/callback/logout routes."""

    @pytest.fixture
    def app_with_oauth(self, tmp_path, monkeypatch):
        """Create app with OAuth configured."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")

        # Mock auth provider - use spec to control which attrs exist
        auth_provider = MagicMock(
            spec=[
                "base_url",
                "client_id",
                "client_secret",
                "upstream_token_endpoint",
            ]
        )
        auth_provider.base_url = "https://auth.example.com"
        auth_provider.client_id = "test-client"
        auth_provider.client_secret = "test-secret"
        auth_provider.upstream_token_endpoint = "https://auth.example.com/token"

        routes = create_web_ui_routes(
            path_prefix="/config",
            check_auth=None,
            auth_provider=auth_provider,
        )
        return Starlette(routes=routes)

    @pytest.fixture
    def app_no_oauth(self, tmp_path, monkeypatch):
        """Create app without OAuth configured."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")

        routes = create_web_ui_routes(
            path_prefix="/config",
            check_auth=None,
            auth_provider=None,
        )
        return Starlette(routes=routes)

    def test_login_page_redirects_to_oauth(self, app_with_oauth):
        """GET /config/login should redirect to OAuth provider."""
        client = TestClient(app_with_oauth, follow_redirects=False)
        response = client.get("/config/login")
        assert response.status_code == 302
        location = response.headers["location"]
        assert "auth.example.com/authorize" in location
        assert "client_id=test-client" in location

    def test_login_page_no_oauth_configured(self, app_no_oauth):
        """GET /config/login should return error when OAuth not configured."""
        client = TestClient(app_no_oauth)
        response = client.get("/config/login")
        assert response.status_code == 500
        assert "OAuth Not Configured" in response.text

    def test_login_callback_no_code(self, app_with_oauth):
        """GET /config/login/callback without code should return error."""
        client = TestClient(app_with_oauth)
        response = client.get("/config/login/callback?error=access_denied")
        assert response.status_code == 400
        assert "Login Failed" in response.text

    def test_login_callback_no_token_url(self, tmp_path, monkeypatch):
        """GET /config/login/callback should fail when token_url unavailable."""
        from starlette.applications import Starlette

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test")

        # Provider with no token URL attributes (empty spec = no attrs exist)
        # This hits line 632 when _get_token_url returns None
        auth_provider = MagicMock(spec=[])

        routes = create_web_ui_routes(
            path_prefix="/config",
            check_auth=None,
            auth_provider=auth_provider,
        )
        app = Starlette(routes=routes)
        client = TestClient(app)
        response = client.get("/config/login/callback?code=test-code")
        assert response.status_code == 500
        assert "OAuth Not Configured" in response.text

    def test_login_callback_with_code_success(self, app_with_oauth, monkeypatch):
        """GET /config/login/callback with valid code should set cookie."""
        mock_exchange = AsyncMock(
            return_value={"access_token": "tok", "sub": "user123"}
        )
        monkeypatch.setattr("mcp_proxy.web_ui._exchange_code_for_token", mock_exchange)

        client = TestClient(app_with_oauth, follow_redirects=False)
        response = client.get("/config/login/callback?code=auth-code&state=/config")
        assert response.status_code == 302
        assert SESSION_COOKIE_NAME in response.cookies

    def test_login_callback_token_exchange_fails(self, app_with_oauth, monkeypatch):
        """GET /config/login/callback should handle token exchange failure."""
        mock_exchange = AsyncMock(return_value=None)
        monkeypatch.setattr("mcp_proxy.web_ui._exchange_code_for_token", mock_exchange)

        client = TestClient(app_with_oauth)
        response = client.get("/config/login/callback?code=bad-code")
        assert response.status_code == 500
        assert "Token Exchange Failed" in response.text

    def test_logout_clears_cookie(self, app_with_oauth, monkeypatch):
        """GET /config/logout should clear session cookie."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "secret")
        client = TestClient(app_with_oauth, follow_redirects=False)

        # First, set a cookie
        client.cookies.set(SESSION_COOKIE_NAME, create_session_cookie("user"))

        response = client.get("/config/logout")
        assert response.status_code == 302
        # Cookie should be deleted (max-age=0 or expires in past)
        assert response.headers["location"] == "/config"


class TestBrowserAuthFlow:
    """Tests for browser authentication flow."""

    @pytest.fixture
    def app_with_auth_check(self, tmp_path, monkeypatch):
        """Create app with auth check that rejects requests."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")

        async def reject_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        auth_provider = MagicMock(spec=["base_url", "client_id"])
        auth_provider.base_url = "https://auth.example.com"
        auth_provider.client_id = "test-client"

        routes = create_web_ui_routes(
            path_prefix="/config",
            check_auth=reject_auth,
            auth_provider=auth_provider,
        )
        return Starlette(routes=routes)

    def test_browser_request_redirects_to_login(self, app_with_auth_check):
        """Browser request without session should redirect to login."""
        client = TestClient(app_with_auth_check, follow_redirects=False)
        response = client.get("/config", headers={"Accept": "text/html"})
        assert response.status_code == 302
        assert "/config/login" in response.headers["location"]

    def test_api_request_gets_401(self, app_with_auth_check):
        """API request without token should get 401."""
        client = TestClient(app_with_auth_check)
        response = client.get("/config", headers={"Accept": "application/json"})
        assert response.status_code == 401

    def test_valid_session_cookie_allows_access(self, app_with_auth_check, monkeypatch):
        """Request with valid session cookie should be allowed."""
        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")
        cookie = create_session_cookie("user123")

        client = TestClient(app_with_auth_check)
        client.cookies.set(SESSION_COOKIE_NAME, cookie)
        response = client.get("/config", headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert "MCP Proxy Configuration" in response.text

    def test_expired_session_redirects(self, app_with_auth_check, monkeypatch):
        """Request with expired session should redirect to login."""
        import json

        monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")
        # Create an expired session
        expires = int(time.time()) - 100
        data = json.dumps({"user_id": "test", "expires": expires})
        cookie = _sign_session_data(data)

        client = TestClient(app_with_auth_check, follow_redirects=False)
        client.cookies.set(SESSION_COOKIE_NAME, cookie)
        response = client.get("/config", headers={"Accept": "text/html"})
        assert response.status_code == 302
        assert "/config/login" in response.headers["location"]


class TestBrowserNoAuthProvider:
    """Tests for browser flow when no auth provider is configured."""

    @pytest.fixture
    def app_no_auth_provider(self, tmp_path, monkeypatch):
        """Create app without auth provider but with auth check."""
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"mcp_servers": {}, "tool_views": {}}))
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        async def reject_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        routes = create_web_ui_routes(
            path_prefix="/config",
            check_auth=reject_auth,
            auth_provider=None,  # No OAuth configured
        )
        return Starlette(routes=routes)

    def test_browser_shows_error_without_oauth(self, app_no_auth_provider):
        """Browser request without OAuth should show error message."""
        client = TestClient(app_no_auth_provider)
        response = client.get("/config", headers={"Accept": "text/html"})
        assert response.status_code == 401
        assert "Authentication Required" in response.text
        assert "OAuth is not configured" in response.text
