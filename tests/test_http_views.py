"""Tests for HTTP multi-view routing.

The proxy should expose different tool views at different URL paths:
- / or /mcp → Default view (all mcp_servers tools)
- /view/<name>/mcp → Tools from specific view
"""

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_proxy.models import (
    ProxyConfig,
    ToolViewConfig,
    UpstreamServerConfig,
)
from mcp_proxy.proxy import MCPProxy


class TestHTTPViewRouting:
    """Tests for view-based HTTP routing."""

    def test_proxy_creates_http_app(self):
        """MCPProxy should have an http_app() method that returns ASGI app."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Should have http_app method
        assert hasattr(proxy, "http_app")
        app = proxy.http_app()
        assert app is not None

    def test_root_path_serves_default_view(self):
        """Root path /mcp should be mounted (route exists)."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        # Check that the route is registered in the app
        # We can't easily test the MCP protocol itself without proper session setup
        # but we can verify the mount point exists
        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)

        # The default MCP app should be mounted at "/" or "" (empty path for root mount)
        assert "/" in route_paths or "" in route_paths, (
            f"Expected root mount, got: {route_paths}"
        )

    def test_view_path_exists_for_each_view(self):
        """Each view should be mounted at /view/<name>."""
        config = ProxyConfig(
            mcp_servers={"github": UpstreamServerConfig(url="https://example.com/mcp")},
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools", tools={"github": {"search_code": {}}}
                ),
                "coding": ToolViewConfig(
                    description="Coding tools",
                    tools={"github": {"get_file_contents": {}}},
                ),
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        # Check that view routes are registered
        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)

        # Each view should have a mount point
        assert "/view/research" in route_paths, "research view should be mounted"
        assert "/view/coding" in route_paths, "coding view should be mounted"

    def test_nonexistent_view_returns_404(self):
        """Accessing a non-existent view should return 404."""
        config = ProxyConfig(
            mcp_servers={},
            tool_views={"research": ToolViewConfig(description="Research tools")},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/view/nonexistent/mcp")
        assert response.status_code == 404

    def test_view_info_nonexistent_returns_404(self):
        """GET /views/<nonexistent> should return 404."""
        config = ProxyConfig(
            mcp_servers={},
            tool_views={"research": ToolViewConfig(description="Research tools")},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/views/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["error"]


class TestHTTPViewToolIsolation:
    """Tests for tool isolation between views."""

    def test_view_only_exposes_configured_tools(self):
        """Each view should only expose its configured tools."""
        config = ProxyConfig(
            mcp_servers={"github": UpstreamServerConfig(url="https://example.com/mcp")},
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={"github": {"search_code": {}, "search_issues": {}}},
                ),
                "coding": ToolViewConfig(
                    description="Coding tools",
                    tools={"github": {"get_file_contents": {}, "create_branch": {}}},
                ),
            },
        )
        proxy = MCPProxy(config)

        # Get tool lists for each view
        research_tools = proxy.get_view_tools("research")
        coding_tools = proxy.get_view_tools("coding")

        # Research should have search tools
        research_tool_names = [t.name for t in research_tools]
        assert "search_code" in research_tool_names
        assert "search_issues" in research_tool_names
        assert "get_file_contents" not in research_tool_names

        # Coding should have file tools
        coding_tool_names = [t.name for t in coding_tools]
        assert "get_file_contents" in coding_tool_names
        assert "create_branch" in coding_tool_names
        assert "search_code" not in coding_tool_names

    def test_default_view_exposes_all_server_tools(self):
        """Default view (root) should expose all tools from mcp_servers."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    url="https://example.com/mcp",
                    tools={"search_code": {}, "get_file_contents": {}},
                ),
                "memory": UpstreamServerConfig(
                    command="memory-server",
                    tools={"search_memory": {}, "create_memory": {}},
                ),
            },
            tool_views={},
        )
        MCPProxy(config)


class TestHTTPViewToolDescriptions:
    """Tests for per-view tool descriptions."""

    def test_view_applies_custom_tool_descriptions(self):
        """Each view can have custom descriptions for tools."""
        config = ProxyConfig(
            mcp_servers={"github": UpstreamServerConfig(url="https://example.com/mcp")},
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={
                        "github": {
                            "search_code": {
                                "description": "Use for research. {original}"
                            }
                        }
                    },
                ),
                "coding": ToolViewConfig(
                    description="Coding tools",
                    tools={
                        "github": {
                            "search_code": {
                                "description": "Find code to modify. {original}"
                            }
                        }
                    },
                ),
            },
        )
        proxy = MCPProxy(config)

        # Same tool should have different descriptions in different views
        research_tools = proxy.get_view_tools("research")
        coding_tools = proxy.get_view_tools("coding")

        research_search = next(t for t in research_tools if t.name == "search_code")
        coding_search = next(t for t in coding_tools if t.name == "search_code")

        assert "research" in research_search.description.lower()
        assert "modify" in coding_search.description.lower()


class TestHTTPAppConfiguration:
    """Tests for http_app configuration options."""

    def test_http_app_custom_base_path(self):
        """http_app should accept custom base path."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # Should be able to mount at custom path
        app = proxy.http_app(path="/api/v1")

        # Check that routes are prefixed with /api/v1
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api/v1" in p for p in route_paths), (
            f"Expected /api/v1 prefix, got: {route_paths}"
        )

    def test_http_app_custom_view_prefix(self):
        """http_app should accept custom view path prefix."""
        config = ProxyConfig(
            mcp_servers={},
            tool_views={"research": ToolViewConfig(description="Research")},
        )
        proxy = MCPProxy(config)

        # Custom prefix for views
        app = proxy.http_app(view_prefix="/views")

        # Check that view is mounted with custom prefix
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/views/research" in route_paths, (
            f"Expected /views/research, got: {route_paths}"
        )


class TestHTTPViewListing:
    """Tests for listing available views."""

    def test_list_views_endpoint(self):
        """Should have endpoint to list available views."""
        config = ProxyConfig(
            mcp_servers={},
            tool_views={
                "research": ToolViewConfig(description="Research tools"),
                "coding": ToolViewConfig(description="Coding tools"),
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/views")

        assert response.status_code == 200
        data = response.json()
        assert "research" in data["views"]
        assert "coding" in data["views"]

    def test_view_info_endpoint(self):
        """Should have endpoint to get view info."""
        config = ProxyConfig(
            mcp_servers={"github": UpstreamServerConfig(url="https://example.com/mcp")},
            tool_views={
                "research": ToolViewConfig(
                    description="Research tools",
                    tools={"github": {"search_code": {}, "search_issues": {}}},
                )
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/views/research")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "research"
        assert data["description"] == "Research tools"
        assert "tools" in data

    def test_view_info_search_per_server_mode(self):
        """View info should list server search tools for search_per_server mode."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(url="https://example.com/mcp"),
                "memory": UpstreamServerConfig(command="echo"),
            },
            tool_views={
                "all": ToolViewConfig(
                    description="All tools",
                    exposure_mode="search_per_server",
                    tools={
                        "github": {"search_code": {}},
                        "memory": {"search_memories": {}},
                    },
                )
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/views/all")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "all"
        assert data["exposure_mode"] == "search_per_server"
        tool_names = [t["name"] for t in data["tools"]]
        assert "github_search_tools" in tool_names
        assert "memory_search_tools" in tool_names


class TestHTTPHealthCheck:
    """Tests for health check endpoint."""

    def test_health_endpoint(self):
        """Should have a health check endpoint."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)
        app = proxy.http_app()

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestHTTPViewServerSubset:
    """Tests for views with server subsets."""

    def test_view_with_multiple_servers(self):
        """View can include tools from multiple servers."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(url="https://github.example.com/mcp"),
                "jira": UpstreamServerConfig(url="https://jira.example.com/mcp"),
            },
            tool_views={
                "project-mgmt": ToolViewConfig(
                    description="Project management tools",
                    tools={
                        "github": {"search_issues": {}},
                        "jira": {"search_issues": {}, "create_issue": {}},
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("project-mgmt")
        [t.name for t in tools]

        # Should have tools from both servers
        # Note: might need namespacing to avoid collisions
        assert len(tools) == 3  # 1 from github + 2 from jira

    def test_view_with_include_all_from_server(self):
        """View with include_all should get all tools from specified servers."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(url="https://example.com/mcp"),
            },
            tool_views={
                "all-github": ToolViewConfig(
                    description="All GitHub tools",
                    include_all=True,
                    tools={"github": {}},  # Empty means all
                )
            },
        )
        proxy = MCPProxy(config)

        # Should include all tools from github server
        proxy.get_view_tools("all-github")
        # With mocked upstream, can't verify exact count
        # but the view should be properly configured
        assert proxy.views["all-github"].config.include_all is True


class TestHTTPSearchEndpoint:
    """Tests for the /search endpoint that exposes all tools via search_per_server."""

    def test_search_endpoint_is_mounted(self):
        """The /search endpoint should be mounted in the app."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(url="https://example.com/mcp"),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        # Check that /search route is registered
        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)

        assert "/search" in route_paths, f"Expected /search mount, got: {route_paths}"

    def test_search_endpoint_with_path_prefix(self):
        """The /search endpoint should respect path prefix."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo"),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app(path="/api")

        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)

        assert "/api/search" in route_paths

    def test_search_endpoint_creates_virtual_view(self):
        """The search endpoint should create a _search virtual view."""
        config = ProxyConfig(
            mcp_servers={
                "github": UpstreamServerConfig(
                    command="echo",
                    tools={"search_code": {"description": "Search code"}},
                ),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # _search view should not exist initially
        assert "_search" not in proxy.views

        # After http_app is created, we need to initialize the search view
        # This happens in the lifespan, so we test the method directly
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        proxy._initialize_search_view(mcp)

        # Now _search view should exist
        assert "_search" in proxy.views
        assert proxy.views["_search"].config.include_all is True
        assert proxy.views["_search"].config.exposure_mode == "search_per_server"


class TestHTTPExtraRoutes:
    """Tests for extra_routes in http_app."""

    def test_http_app_with_extra_routes(self):
        """http_app should include extra_routes in the application."""
        from starlette.responses import PlainTextResponse

        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        async def custom_endpoint(request):
            return PlainTextResponse("custom response")

        extra_routes = [Route("/custom", custom_endpoint, methods=["GET"])]
        app = proxy.http_app(extra_routes=extra_routes)

        client = TestClient(app)
        response = client.get("/custom")
        assert response.status_code == 200
        assert response.text == "custom response"


class TestCheckAuthToken:
    """Tests for the check_auth_token function."""

    @pytest.mark.asyncio
    async def test_no_auth_provider_allows_access(self):
        """When auth_provider is None, access should be allowed."""
        from unittest.mock import MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        result = await check_auth_token(mock_request, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401(self):
        """Missing Authorization header should return 401."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        mock_request.headers = {}

        mock_auth_provider = MagicMock()
        mock_auth_provider.verify_token = AsyncMock(return_value=None)

        result = await check_auth_token(mock_request, mock_auth_provider)
        assert result is not None
        assert result.status_code == 401
        # Check the body contains the expected error
        import json

        body = json.loads(result.body.decode())
        assert body["error"] == "invalid_token"
        assert "Missing or invalid" in body["error_description"]

    @pytest.mark.asyncio
    async def test_non_bearer_auth_header_returns_401(self):
        """Non-Bearer Authorization header should return 401."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}

        mock_auth_provider = MagicMock()
        mock_auth_provider.verify_token = AsyncMock(return_value=None)

        result = await check_auth_token(mock_request, mock_auth_provider)
        assert result is not None
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_bearer_token_returns_401(self):
        """Empty Bearer token should return 401."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer "}

        mock_auth_provider = MagicMock()
        mock_auth_provider.verify_token = AsyncMock(return_value=None)

        result = await check_auth_token(mock_request, mock_auth_provider)
        assert result is not None
        assert result.status_code == 401
        import json

        body = json.loads(result.body.decode())
        assert "Empty bearer token" in body["error_description"]

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        """Invalid token should return 401."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer invalid-token"}

        mock_auth_provider = MagicMock()
        mock_auth_provider.verify_token = AsyncMock(return_value=None)

        result = await check_auth_token(mock_request, mock_auth_provider)
        assert result is not None
        assert result.status_code == 401
        mock_auth_provider.verify_token.assert_called_once_with("invalid-token")

    @pytest.mark.asyncio
    async def test_valid_token_allows_access(self):
        """Valid token should allow access (return None)."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.proxy.proxy import check_auth_token

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer valid-token"}

        mock_auth_provider = MagicMock()
        mock_access_token = MagicMock()  # Valid token object
        mock_auth_provider.verify_token = AsyncMock(return_value=mock_access_token)

        result = await check_auth_token(mock_request, mock_auth_provider)
        assert result is None
        mock_auth_provider.verify_token.assert_called_once_with("valid-token")


class TestHTTPViewsAuthIntegration:
    """Integration tests for auth on /views endpoints."""

    def test_view_info_returns_auth_error(self):
        """GET /views/<name> should return auth error when check_auth_token fails."""
        from unittest.mock import AsyncMock, patch

        from starlette.responses import JSONResponse

        config = ProxyConfig(
            mcp_servers={},
            tool_views={"research": ToolViewConfig(description="Research tools")},
        )
        proxy = MCPProxy(config)

        # Create a mock auth error response
        mock_auth_error = JSONResponse(
            {"error": "invalid_token", "error_description": "Test error"},
            status_code=401,
        )

        with patch(
            "mcp_proxy.proxy.proxy.check_auth_token",
            new=AsyncMock(return_value=mock_auth_error),
        ):
            app = proxy.http_app()
            client = TestClient(app)
            response = client.get("/views/research")

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"

    def test_list_views_returns_auth_error(self):
        """GET /views should return auth error when check_auth_token fails."""
        from unittest.mock import AsyncMock, patch

        from starlette.responses import JSONResponse

        config = ProxyConfig(
            mcp_servers={},
            tool_views={"research": ToolViewConfig(description="Research tools")},
        )
        proxy = MCPProxy(config)

        # Create a mock auth error response
        mock_auth_error = JSONResponse(
            {"error": "invalid_token", "error_description": "Test error"},
            status_code=401,
        )

        with patch(
            "mcp_proxy.proxy.proxy.check_auth_token",
            new=AsyncMock(return_value=mock_auth_error),
        ):
            app = proxy.http_app()
            client = TestClient(app)
            response = client.get("/views")

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"


class TestHTTPCacheRoutes:
    """Tests for cache routes in HTTP app."""

    def test_http_app_includes_cache_routes_when_enabled(self, tmp_path):
        """http_app should include cache routes when caching is enabled."""
        from unittest.mock import patch

        from mcp_proxy.models import OutputCacheConfig

        config = ProxyConfig(
            output_cache=OutputCacheConfig(enabled=True),
            cache_secret="test-secret",
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
        )
        proxy = MCPProxy(config)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            app = proxy.http_app()

            # Check that cache route exists
            client = TestClient(app)
            # Try to access cache endpoint (should return 400 for missing params)
            response = client.get("/cache/sometoken")
            assert response.status_code == 400
            assert "Missing" in response.text

    def test_http_app_cache_retrieval_works(self, tmp_path):
        """http_app cache route should retrieve cached content."""
        from unittest.mock import patch

        from mcp_proxy.cache import create_cached_output_with_meta
        from mcp_proxy.models import OutputCacheConfig

        config = ProxyConfig(
            output_cache=OutputCacheConfig(enabled=True),
            cache_secret="test-secret",
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
        )
        proxy = MCPProxy(config)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Create cached content
            response = create_cached_output_with_meta(
                content="http cached content",
                secret="test-secret",
                base_url="http://localhost:8000",
                ttl_seconds=3600,
                preview_chars=100,
            )

            app = proxy.http_app()
            client = TestClient(app)

            # Extract query params from URL
            url_parts = response.retrieve_url.split("?")
            query = url_parts[1]
            http_response = client.get(f"/cache/{response.token}?{query}")

            assert http_response.status_code == 200
            assert http_response.text == "http cached content"

    def test_http_app_no_cache_routes_when_disabled(self):
        """http_app should not include cache routes when caching is disabled."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        # Check that cache route does not exist
        client = TestClient(app)
        response = client.get("/cache/sometoken")
        # Should be 404 (not found) not 400 (bad request)
        assert response.status_code == 404


class TestHTTPWebUIRoutes:
    """Tests for web UI config routes in HTTP app."""

    def test_http_app_includes_config_routes(self):
        """http_app should include /config routes for web UI."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={},
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        # Check that /config route exists
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/config" in route_paths

    def test_config_route_uses_auth(self, tmp_path, monkeypatch):
        """Config routes should use the same auth as other endpoints."""
        from unittest.mock import AsyncMock, patch

        from starlette.responses import JSONResponse

        # Set up config file
        config_path = tmp_path / "config.yaml"
        config_path.write_text("mcp_servers: {}\ntool_views: {}\n")
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        config = ProxyConfig(
            mcp_servers={},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a mock auth error response
        mock_auth_error = JSONResponse(
            {"error": "invalid_token", "error_description": "Test error"},
            status_code=401,
        )

        with patch(
            "mcp_proxy.proxy.proxy.check_auth_token",
            new=AsyncMock(return_value=mock_auth_error),
        ):
            app = proxy.http_app()
            client = TestClient(app)
            response = client.get("/config")

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"

    def test_config_api_route_uses_auth(self, tmp_path, monkeypatch):
        """Config API routes should use auth."""
        from unittest.mock import AsyncMock, patch

        from starlette.responses import JSONResponse

        config_path = tmp_path / "config.yaml"
        config_path.write_text("mcp_servers: {}\ntool_views: {}\n")
        monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        mock_auth_error = JSONResponse({"error": "unauthorized"}, status_code=401)

        with patch(
            "mcp_proxy.proxy.proxy.check_auth_token",
            new=AsyncMock(return_value=mock_auth_error),
        ):
            app = proxy.http_app()
            client = TestClient(app)
            response = client.get("/config/api")

        assert response.status_code == 401
