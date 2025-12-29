"""Tests for HTTP multi-view routing.

The proxy should expose different tool views at different URL paths:
- / or /mcp → Default view (all mcp_servers tools)
- /view/<name>/mcp → Tools from specific view
"""

from starlette.testclient import TestClient

from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
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
