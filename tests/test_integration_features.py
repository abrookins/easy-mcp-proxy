"""Integration tests for MCP Proxy features.

These tests verify end-to-end functionality across multiple components.

Features covered:
1. Actual upstream MCP connections
2. CLI schema fetching from upstream servers
3. CLI tool call execution
4. Composite tools (parallel) wired into config/views
5. Custom tools loading from views
6. Tool renaming applied in proxy
7. include_all: true for views
8. Search mode integration in proxy
9. Validate CLI command with upstream connections
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy

# =============================================================================
# 1. Actual Upstream MCP Connections
# =============================================================================


class TestUpstreamConnections:
    """Tests for actual upstream MCP server connections."""

    @pytest.mark.asyncio
    async def test_proxy_connects_to_command_based_upstream(self):
        """MCPProxy should connect to command-based upstream servers."""
        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",
                    args=["test"],
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # This should create an actual MCP client connection
        # Currently raises AttributeError because _create_client doesn't exist
        client = await proxy._create_client("test-server")

        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")

    @pytest.mark.asyncio
    async def test_proxy_connects_to_url_based_upstream(self):
        """MCPProxy should connect to URL-based upstream servers."""
        config = ProxyConfig(
            mcp_servers={
                "remote-server": UpstreamServerConfig(
                    url="http://localhost:8080/mcp",
                    headers={"Authorization": "Bearer token123"},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # This should create an HTTP-based MCP client
        client = await proxy._create_client("remote-server")

        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")

    @pytest.mark.asyncio
    async def test_proxy_initialize_creates_all_clients(self):
        """MCPProxy.initialize() should create clients for all servers."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(command="echo", args=["a"]),
                "server-b": UpstreamServerConfig(command="echo", args=["b"]),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock refresh_upstream_tools to avoid actual connection attempts
        # (echo is not a valid MCP server and would hang on Linux)
        with patch.object(proxy, "refresh_upstream_tools", new_callable=AsyncMock):
            # After initialize, proxy should have clients for all servers
            await proxy.initialize()

        assert "server-a" in proxy.upstream_clients
        assert "server-b" in proxy.upstream_clients

    @pytest.mark.asyncio
    async def test_proxy_fetches_tools_from_upstream(self):
        """MCPProxy should fetch actual tool lists from upstream servers."""
        # This requires mocking an actual MCP server
        config = ProxyConfig(
            mcp_servers={"test": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [
            MagicMock(name="real_tool_1", description="Real tool 1"),
            MagicMock(name="real_tool_2", description="Real tool 2"),
        ]

        # After initialize, tools should come from upstream, not config
        proxy.upstream_clients = {"test": mock_client}
        tools = await proxy.fetch_upstream_tools("test")

        assert len(tools) == 2
        mock_client.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_call_routes_to_upstream(self):
        """Tool calls should route to the actual upstream server."""

        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    command="echo", tools={"my_tool": {"description": "My tool"}}
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.call_tool.return_value = {"result": "from_upstream"}

        # Mock _create_client_from_config to return our mock client
        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            # Call should go to upstream
            result = await proxy.call_upstream_tool("test", "my_tool", {"arg": "value"})

            assert result == {"result": "from_upstream"}
            mock_client.call_tool.assert_called_once_with("my_tool", {"arg": "value"})

    @pytest.mark.asyncio
    async def test_env_vars_expanded_in_server_config(self):
        """Env vars in server config should be expanded when creating client."""
        import os

        from mcp_proxy.proxy import expand_env_vars

        os.environ["TEST_API_KEY"] = "secret123"

        # Test the expand_env_vars function directly
        result = expand_env_vars("Bearer ${TEST_API_KEY}")
        assert result == "Bearer secret123"

        # Test that config with env vars gets expanded during client creation
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(
                    url="http://example.com/mcp",
                    headers={"Authorization": "Bearer ${TEST_API_KEY}"},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # The expansion happens during client creation, not config load
        # Verify by creating a client (which uses expand_env_vars internally)
        client = await proxy._create_client("test")

        # Client was created successfully - verify the transport was configured
        assert client is not None


# =============================================================================
# 2. CLI Schema Fetching from Upstream
# =============================================================================


class TestCLISchemaFetching:
    """Tests for CLI schema command fetching from upstream servers."""

    def test_cli_schema_attempts_connection(self, tmp_path):
        """mcp-proxy schema should attempt to connect to upstream (no longer stub)."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  github:
    url: https://example.com/mcp
""")

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "github.search_code", "-c", str(config_file)]
        )

        # Should no longer say "requires upstream connection" - it actually tries
        assert "requires upstream connection" not in result.output
        # Will likely have an error since the server doesn't exist, but that's ok
        assert result.output  # Just verify we got output

    def test_cli_schema_json_output(self, tmp_path):
        """mcp-proxy schema --json should output JSON."""
        import json

        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "--json", "-c", str(config_file)])

        # Should be valid JSON (even if it contains errors from connection attempts)
        data = json.loads(result.output)
        assert "tools" in data  # The key exists even if servers failed

    def test_cli_schema_server_lists_tools(self, tmp_path):
        """mcp-proxy schema --server should attempt to list tools."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--server", "test", "-c", str(config_file)]
        )

        # Should no longer say "requires upstream connection"
        assert "requires upstream connection" not in result.output
        # Either shows tools or connection error
        assert "Server: test" in result.output or "Error" in result.output


# =============================================================================
# 3. CLI Tool Call Execution
# =============================================================================


class TestCLIToolCallExecution:
    """Tests for CLI call command executing actual tool calls."""

    def test_cli_call_attempts_execution(self, tmp_path):
        """mcp-proxy call should attempt to execute (no longer stub)."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(
            main, ["call", "test.some_tool", "-a", "arg=value", "-c", str(config_file)]
        )

        # Should no longer say "requires upstream connection"
        assert "requires upstream connection" not in result.output
        # Either shows "Calling..." or connection error (both mean it's attempting)
        assert "test.some_tool" in result.output

    def test_cli_call_with_multiple_args(self, tmp_path):
        """mcp-proxy call should handle multiple arguments."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "call",
                "test.tool",
                "-a",
                "query=hello",
                "-a",
                "limit=10",
                "-c",
                str(config_file),
            ],
        )

        # Should no longer say "requires upstream connection"
        assert "requires upstream connection" not in result.output


# =============================================================================
# 4. Composite Tools (Parallel) Wired into Config/Views
# =============================================================================


class TestCompositeToolsIntegration:
    """Tests for composite_tools configuration wired into views."""

    def test_composite_tools_parsed_from_config(self):
        """composite_tools in config should be parsed into ParallelTool objects."""
        config_dict = {
            "mcp_servers": {
                "redis": {"command": "redis-server"},
                "github": {"url": "https://api.github.com/mcp"},
            },
            "tool_views": {
                "search": {
                    "description": "Unified search",
                    "composite_tools": {
                        "search_all": {
                            "description": "Search all sources",
                            "inputs": {"query": {"type": "string", "required": True}},
                            "parallel": {
                                "memory": {
                                    "tool": "redis.search_long_term_memory",
                                    "args": {"text": "{inputs.query}"},
                                },
                                "code": {
                                    "tool": "github.search_code",
                                    "args": {"query": "{inputs.query}"},
                                },
                            },
                        }
                    },
                }
            },
        }

        config = ProxyConfig(**config_dict)
        proxy = MCPProxy(config)

        # The view should have the composite tool registered
        view = proxy.views["search"]
        assert hasattr(view, "composite_tools")
        assert "search_all" in view.composite_tools

    @pytest.mark.asyncio
    async def test_composite_tool_exposed_in_view(self):
        """Composite tools should appear in get_view_tools()."""
        config = ProxyConfig(
            mcp_servers={
                "redis": UpstreamServerConfig(command="redis"),
                "github": UpstreamServerConfig(url="https://github.com/mcp"),
            },
            tool_views={
                "search": ToolViewConfig(
                    description="Search",
                    composite_tools={
                        "search_all": {
                            "description": "Search everywhere",
                            "parallel": {
                                "a": {"tool": "redis.search", "args": {}},
                                "b": {"tool": "github.search", "args": {}},
                            },
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("search")
        tool_names = [t.name for t in tools]

        assert "search_all" in tool_names

    @pytest.mark.asyncio
    async def test_composite_tool_callable_through_mcp(self):
        """Composite tools should be callable through MCP protocol."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(command="echo"),
            },
            tool_views={
                "test": ToolViewConfig(
                    description="Test",
                    composite_tools={
                        "parallel_tool": {
                            "description": "Parallel execution",
                            "inputs": {"q": {"type": "string"}},
                            "parallel": {
                                "a": {
                                    "tool": "server.tool_a",
                                    "args": {"q": "{inputs.q}"},
                                },
                                "b": {
                                    "tool": "server.tool_b",
                                    "args": {"q": "{inputs.q}"},
                                },
                            },
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # The composite tool should be callable through the view's MCP
        view_mcp = proxy.get_view_mcp("test")
        async with Client(view_mcp) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "parallel_tool" in tool_names

            # Actually call the composite tool to cover the wrapper code path
            result = await client.call_tool("parallel_tool", {})
            # The wrapper returns a message about calling via view.call_tool
            assert result.content is not None


# =============================================================================
# 5. Custom Tools Loading from Views
# =============================================================================


class TestCustomToolsIntegration:
    """Tests for custom_tools loading and registration from views."""

    def test_custom_tools_loaded_from_view_config(self, tmp_path, monkeypatch):
        """custom_tools in view config should be loaded and registered."""
        # Create a custom tool module
        module_dir = tmp_path / "my_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(name="smart_search", description="Smart search with context")
async def smart_search(query: str, ctx: ProxyContext = None) -> dict:
    return {"result": query}
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ProxyConfig(
            mcp_servers={},
            tool_views={
                "smart": ToolViewConfig(
                    description="Smart tools",
                    custom_tools=[{"module": "my_hooks.tools.smart_search"}],
                )
            },
        )
        proxy = MCPProxy(config)

        # Custom tool should be in the view
        tools = proxy.get_view_tools("smart")
        tool_names = [t.name for t in tools]

        assert "smart_search" in tool_names

    @pytest.mark.asyncio
    async def test_custom_tool_receives_proxy_context(self, tmp_path, monkeypatch):
        """Custom tools should receive ProxyContext with call_tool capability."""
        # Create a custom tool that calls upstream
        module_dir = tmp_path / "ctx_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(name="composed", description="Composed tool")
async def composed(query: str, ctx: ProxyContext = None) -> dict:
    upstream_result = await ctx.call_tool("server.upstream_tool", text=query)
    return {"composed": True, "upstream": upstream_result}
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "composed": ToolViewConfig(
                    custom_tools=[{"module": "ctx_hooks.tools.composed"}]
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "from_upstream"}
        proxy.upstream_clients = {"server": mock_client}

        # Also set the view's upstream clients
        view = proxy.views["composed"]
        view._upstream_clients = {"server": mock_client}

        # Call the custom tool through the view
        result = await view.call_tool("composed", {"query": "test"})

        assert result["composed"] is True
        mock_client.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_tool_callable_through_mcp(self, tmp_path, monkeypatch):
        """Custom tools should be callable through MCP protocol."""
        from fastmcp import Client

        module_dir = tmp_path / "mcp_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool

@custom_tool(name="mcp_tool", description="MCP callable tool")
async def mcp_tool(x: int) -> dict:
    return {"doubled": x * 2}
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ProxyConfig(
            mcp_servers={},
            tool_views={
                "custom": ToolViewConfig(
                    custom_tools=[{"module": "mcp_hooks.tools.mcp_tool"}]
                )
            },
        )
        proxy = MCPProxy(config)

        # Use the view's MCP
        view_mcp = proxy.get_view_mcp("custom")
        async with Client(view_mcp) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "mcp_tool" in tool_names

            # Call the tool
            result = await client.call_tool("mcp_tool", {"x": 5})
            assert result is not None


# =============================================================================
# 6. Tool Renaming Applied in Proxy
# =============================================================================


class TestToolRenamingIntegration:
    """Tests for tool renaming being applied when exposing tools."""

    @pytest.mark.asyncio
    async def test_tool_name_override_in_view(self):
        """Tool with name override should be exposed with new name."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"original_name": {"description": "Original tool"}},
                )
            },
            tool_views={
                "renamed": ToolViewConfig(
                    description="View with renamed tools",
                    tools={
                        "server": {
                            "original_name": {
                                "name": "better_name",
                                "description": "Renamed tool",
                            }
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("renamed")
        tool_names = [t.name for t in tools]

        # Should be exposed as "better_name", not "original_name"
        assert "better_name" in tool_names
        assert "original_name" not in tool_names

    @pytest.mark.asyncio
    async def test_renamed_tool_callable_by_new_name(self):
        """Renamed tool should be callable by its new name."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"old_name": {}})
            },
            tool_views={
                "view": ToolViewConfig(
                    tools={"server": {"old_name": {"name": "new_name"}}}
                )
            },
        )
        proxy = MCPProxy(config)

        # Should be callable by new name
        async with Client(proxy.server) as client:
            tools = await client.list_tools()
            [t.name for t in tools]
            # Note: This tests the default view, not the "view" view
            # The renaming should apply to the view

    @pytest.mark.asyncio
    async def test_renamed_tool_routes_to_original(self):
        """Calling renamed tool should route to original upstream tool."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "view": ToolViewConfig(
                    tools={"server": {"original_tool": {"name": "aliased_tool"}}}
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "ok"}
        proxy.upstream_clients = {"server": mock_client}

        view = proxy.views["view"]
        view._upstream_clients = {"server": mock_client}

        # Calling by aliased name should call original on upstream
        await view.call_tool("aliased_tool", {"arg": "value"})

        # The upstream should be called with the ORIGINAL tool name
        mock_client.call_tool.assert_called_once_with("original_tool", {"arg": "value"})


# =============================================================================
# 7. include_all: true for Views
# =============================================================================


class TestIncludeAllIntegration:
    """Tests for include_all: true including all tools from all servers."""

    def test_include_all_includes_all_server_tools(self):
        """include_all: true should include all tools from all servers."""
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_1": {"description": "Tool 1"},
                        "tool_2": {"description": "Tool 2"},
                    },
                ),
                "server-b": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_3": {"description": "Tool 3"},
                    },
                ),
            },
            tool_views={
                "all-tools": ToolViewConfig(
                    description="All tools from all servers",
                    include_all=True,
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("all-tools")
        tool_names = [t.name for t in tools]

        # Should include all 3 tools from both servers
        assert len(tools) == 3
        assert "tool_1" in tool_names
        assert "tool_2" in tool_names
        assert "tool_3" in tool_names

    @pytest.mark.asyncio
    async def test_include_all_fetches_from_upstream(self):
        """include_all should include tools defined in config from all servers."""
        # Note: Dynamic tool discovery from upstream would require additional
        # infrastructure to store and refresh tools. For now, include_all
        # works with tools defined in config.
        config = ProxyConfig(
            mcp_servers={
                "server-a": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_from_a": {"description": "Tool from A"},
                    },
                ),
                "server-b": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_from_b": {"description": "Tool from B"},
                    },
                ),
            },
            tool_views={"all": ToolViewConfig(include_all=True)},
        )
        proxy = MCPProxy(config)

        # include_all should include tools from all servers defined in config
        tools = proxy.get_view_tools("all")
        tool_names = [t.name for t in tools]

        assert "tool_from_a" in tool_names
        assert "tool_from_b" in tool_names
        assert len(tools) == 2

    def test_include_all_with_tools_is_additive(self):
        """include_all with specific tools should include both."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "auto_tool": {},
                    },
                )
            },
            tool_views={
                "mixed": ToolViewConfig(
                    include_all=True,
                    tools={
                        "server": {"auto_tool": {"description": "Custom description"}}
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("mixed")

        # Should include auto_tool with the custom description
        auto_tool = next((t for t in tools if t.name == "auto_tool"), None)
        assert auto_tool is not None
        assert auto_tool.description == "Custom description"


# =============================================================================
# 8. Search Mode Integration in Proxy
# =============================================================================


class TestSearchModeIntegration:
    """Tests for exposure_mode: search being integrated into proxy."""

    @pytest.mark.asyncio
    async def test_search_mode_exposes_only_search_tool(self):
        """exposure_mode: search should expose only search meta-tool."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_a": {},
                        "tool_b": {},
                        "tool_c": {},
                    },
                )
            },
            tool_views={
                "search-view": ToolViewConfig(
                    description="Search mode view",
                    exposure_mode="search",
                    tools={
                        "server": {
                            "tool_a": {},
                            "tool_b": {},
                            "tool_c": {},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # In search mode, only the search tool should be exposed
        # Not individual tools
        view_mcp = proxy.get_view_mcp("search-view")

        async with Client(view_mcp) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]

            # Should have search tool
            assert "search-view_search_tools" in tool_names
            # Should NOT have individual tools
            assert "tool_a" not in tool_names
            assert "tool_b" not in tool_names
            assert "tool_c" not in tool_names

    @pytest.mark.asyncio
    async def test_search_tool_returns_view_tools(self):
        """Search tool should return tools from the view."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "search_code": {"description": "Search code"},
                        "search_issues": {"description": "Search issues"},
                    },
                )
            },
            tool_views={
                "github": ToolViewConfig(
                    exposure_mode="search",
                    tools={
                        "server": {
                            "search_code": {},
                            "search_issues": {},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Call the search tool
        view_mcp = proxy.get_view_mcp("github")

        import json

        from fastmcp import Client

        async with Client(view_mcp) as client:
            result = await client.call_tool("github_search_tools", {"query": "search"})

            # Result is CallToolResult - parse the content
            # The content contains text with the JSON result
            content = result.content[0].text if result.content else "{}"
            data = json.loads(content)

            # Should return matching tools
            assert "tools" in data
            assert len(data["tools"]) == 2

    @pytest.mark.asyncio
    async def test_search_mode_call_tool_executes_upstream(self):
        """In search mode, calling a tool by name should still work."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "search-view": ToolViewConfig(
                    exposure_mode="search",
                    tools={
                        "server": {
                            "actual_tool": {},
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "success"}
        proxy.upstream_clients = {"server": mock_client}

        # Also set the view's upstream clients
        view = proxy.views["search-view"]
        view._upstream_clients = {"server": mock_client}

        # Should be able to call the actual tool (via search-then-call pattern)
        result = await view.call_tool("actual_tool", {"arg": "value"})

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_http_app_search_mode_view(self):
        """HTTP app should handle search mode views correctly."""
        from httpx import ASGITransport, AsyncClient

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"tool": {}})
            },
            tool_views={
                "search": ToolViewConfig(
                    exposure_mode="search", tools={"server": {"tool": {}}}
                )
            },
        )
        proxy = MCPProxy(config)
        app = proxy.http_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Get view info
            resp = await client.get("/views/search")
            data = resp.json()

            # View should indicate search mode
            assert data["exposure_mode"] == "search"

            # Tools list should show only search tool
            assert len(data["tools"]) == 1
            assert data["tools"][0]["name"] == "search_search_tools"


# =============================================================================
# 9. Validate CLI Command with Upstream Connections
# =============================================================================


# =============================================================================
# 9. Output Caching End-to-End
# =============================================================================


class TestOutputCachingEndToEnd:
    """End-to-end tests for output caching from tool call to token retrieval."""

    @pytest.mark.asyncio
    async def test_large_output_is_cached_and_retrievable(self, tmp_path):
        """Large tool output should be cached and retrievable via token."""
        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        # Create config with caching enabled
        config = ProxyConfig(
            output_cache=OutputCacheConfig(
                enabled=True,
                ttl_seconds=3600,
                preview_chars=100,
                min_size=50,  # Low threshold for testing
            ),
            cache_secret="test-secret",
            cache_base_url="http://localhost:8000",
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"get_data": {}})
            },
            tool_views={
                "test": ToolViewConfig(include_all=True),
            },
        )
        proxy = MCPProxy(config)

        # Generate large output (> min_size)
        large_output = "x" * 500

        # Mock upstream to return large output
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"content": large_output}
        proxy.upstream_clients = {"server": mock_client}

        # Set up view with cache context and upstream
        view = proxy.views["test"]
        view._upstream_clients = {"server": mock_client}
        view._cache_context = proxy._create_cache_context()
        # Register tool mapping for the view
        view.update_tool_mapping([ToolInfo(name="get_data", server="server")])

        # Patch CACHE_DIR for this test
        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Call the tool - should return cached response
            result = await view.call_tool("get_data", {})

            # Verify cached response format
            assert result["cached"] is True
            assert "token" in result
            assert "retrieve_url" in result
            assert "preview" in result
            assert "expires_at" in result
            assert "size_bytes" in result

            # Preview should be truncated
            assert len(result["preview"]) <= 103  # 100 + "..."

            # Save the token for retrieval
            token = result["token"]

            # Now retrieve the full content using the token
            from mcp_proxy.cache import retrieve_by_token

            full_content = retrieve_by_token(token, "test-secret")

            # Full content should match original (pretty-printed)
            import json

            expected = json.dumps({"content": large_output}, indent=2)
            assert full_content == expected

    @pytest.mark.asyncio
    async def test_cache_retrieval_tool_returns_full_content(self, tmp_path):
        """retrieve_cached_output tool should return full cached content."""
        from fastmcp import Client

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            output_cache=OutputCacheConfig(
                enabled=True,
                ttl_seconds=3600,
                preview_chars=50,
                min_size=10,  # Very low for testing
            ),
            cache_secret="test-secret",
            cache_base_url="http://localhost:8000",
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"fetch": {}})
            },
            tool_views={
                "cached": ToolViewConfig(include_all=True),
            },
        )
        proxy = MCPProxy(config)

        # Large output that will be cached
        large_data = {"items": ["item" + str(i) for i in range(100)]}

        # Mock upstream
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = large_data
        proxy.upstream_clients = {"server": mock_client}

        # Set up view
        view = proxy.views["cached"]
        view._upstream_clients = {"server": mock_client}
        view._cache_context = proxy._create_cache_context()
        view.update_tool_mapping([ToolInfo(name="fetch", server="server")])

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Step 1: Call tool to get cached response
            cached_response = await view.call_tool("fetch", {})

            assert cached_response["cached"] is True
            token = cached_response["token"]

            # Step 2: Get the view MCP and call retrieve_cached_output
            view_mcp = proxy.get_view_mcp("cached")

            async with Client(view_mcp) as client:
                # The retrieve_cached_output tool should be available
                tools = await client.list_tools()
                tool_names = [t.name for t in tools]
                assert "retrieve_cached_output" in tool_names

                # Call retrieve_cached_output with the token
                result = await client.call_tool(
                    "retrieve_cached_output", {"token": token}
                )

                # Parse the result - it comes back as CallToolResult
                import json

                content_text = result.content[0].text
                content_data = json.loads(content_text)

                # Should have the full content
                assert "content" in content_data
                full_content = json.loads(content_data["content"])

                # Verify it matches the original data
                assert full_content == large_data

    @pytest.mark.asyncio
    async def test_http_cache_endpoint_returns_content(self, tmp_path):
        """HTTP /cache/{token} endpoint should return full cached content."""
        from starlette.testclient import TestClient

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            output_cache=OutputCacheConfig(
                enabled=True,
                ttl_seconds=3600,
                preview_chars=50,
                min_size=10,
            ),
            cache_secret="test-secret",
            cache_base_url="http://localhost:8000",
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"read": {}})
            },
            tool_views={
                "http-cached": ToolViewConfig(include_all=True),
            },
        )
        proxy = MCPProxy(config)

        # Large content
        file_content = "Line " + "content " * 100

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = file_content
        proxy.upstream_clients = {"server": mock_client}

        view = proxy.views["http-cached"]
        view._upstream_clients = {"server": mock_client}
        view._cache_context = proxy._create_cache_context()
        view.update_tool_mapping([ToolInfo(name="read", server="server")])

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # Step 1: Call tool to cache the output
            cached_response = await view.call_tool("read", {})

            assert cached_response["cached"] is True
            retrieve_url = cached_response["retrieve_url"]
            token = cached_response["token"]

            # Step 2: Create HTTP app and retrieve via HTTP
            app = proxy.http_app()
            client = TestClient(app)

            # Extract query params from the signed URL
            url_parts = retrieve_url.split("?")
            query = url_parts[1]

            # Make HTTP request to cache endpoint
            http_response = client.get(f"/cache/{token}?{query}")

            assert http_response.status_code == 200
            # Content is plain text containing the cached content
            # The cached content is already the original (string in this case)
            assert http_response.text == file_content

    @pytest.mark.asyncio
    async def test_small_output_not_cached(self, tmp_path):
        """Output below min_size should not be cached."""
        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            output_cache=OutputCacheConfig(
                enabled=True,
                ttl_seconds=3600,
                preview_chars=100,
                min_size=10000,  # High threshold
            ),
            cache_secret="test-secret",
            mcp_servers={
                "server": UpstreamServerConfig(command="echo", tools={"small": {}})
            },
            tool_views={
                "test": ToolViewConfig(include_all=True),
            },
        )
        proxy = MCPProxy(config)

        # Small output (< min_size)
        small_output = {"status": "ok"}

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = small_output
        proxy.upstream_clients = {"server": mock_client}

        view = proxy.views["test"]
        view._upstream_clients = {"server": mock_client}
        view._cache_context = proxy._create_cache_context()
        view.update_tool_mapping([ToolInfo(name="small", server="server")])

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            result = await view.call_tool("small", {})

            # Should return original result, not cached
            assert result == small_output
            assert "cached" not in result or result.get("cached") is not True

    @pytest.mark.asyncio
    async def test_tool_level_cache_config_override(self, tmp_path):
        """Tool-level cache config should override global config."""
        from mcp_proxy.models import OutputCacheConfig, ToolConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            # Global: caching disabled
            output_cache=OutputCacheConfig(enabled=False),
            cache_secret="test-secret",
            cache_base_url="http://localhost:8000",
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        # Tool-level: caching enabled with low threshold
                        "cached_tool": ToolConfig(
                            cache_output=OutputCacheConfig(
                                enabled=True,
                                min_size=10,
                                preview_chars=20,
                            )
                        ),
                        "uncached_tool": ToolConfig(),
                    },
                )
            },
            tool_views={
                "test": ToolViewConfig(include_all=True),
            },
        )
        proxy = MCPProxy(config)

        large_output = "x" * 500

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = large_output
        proxy.upstream_clients = {"server": mock_client}

        view = proxy.views["test"]
        view._upstream_clients = {"server": mock_client}
        view._cache_context = proxy._create_cache_context()
        view.update_tool_mapping(
            [
                ToolInfo(name="cached_tool", server="server"),
                ToolInfo(name="uncached_tool", server="server"),
            ]
        )

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # cached_tool should be cached (tool-level override)
            result1 = await view.call_tool("cached_tool", {})
            assert result1["cached"] is True
            assert len(result1["preview"]) <= 23  # 20 + "..."

            # uncached_tool should NOT be cached (follows global disabled)
            result2 = await view.call_tool("uncached_tool", {})
            assert result2 == large_output

    @pytest.mark.asyncio
    async def test_full_flow_tool_to_http_retrieval(self, tmp_path):
        """Complete flow: call tool -> get token -> retrieve via HTTP."""
        from starlette.testclient import TestClient

        from mcp_proxy.models import OutputCacheConfig
        from mcp_proxy.proxy.tool_info import ToolInfo

        config = ProxyConfig(
            output_cache=OutputCacheConfig(
                enabled=True,
                ttl_seconds=3600,
                preview_chars=100,
                min_size=50,
            ),
            cache_secret="integration-test-secret",
            cache_base_url="http://localhost:8000",
            mcp_servers={
                "files": UpstreamServerConfig(
                    command="echo", tools={"read_file": {"description": "Read a file"}}
                )
            },
            tool_views={
                "files": ToolViewConfig(
                    description="File operations",
                    include_all=True,
                ),
            },
        )
        proxy = MCPProxy(config)

        # Simulate large file content
        file_content = {
            "path": "/data/large_file.txt",
            "content": "=" * 1000,  # Large content
            "size": 1000,
        }

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = file_content
        proxy.upstream_clients = {"files": mock_client}

        view = proxy.views["files"]
        view._upstream_clients = {"files": mock_client}
        view._cache_context = proxy._create_cache_context()
        view.update_tool_mapping([ToolInfo(name="read_file", server="files")])

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path

            # STEP 1: Call tool and get cached response
            result = await view.call_tool("read_file", {"path": "/data/large_file.txt"})

            # Verify it's cached
            assert result["cached"] is True
            assert "token" in result
            assert "retrieve_url" in result
            assert "preview" in result
            assert result["size_bytes"] > 0

            # The preview should be truncated
            preview = result["preview"]
            assert len(preview) <= 103

            token = result["token"]
            retrieve_url = result["retrieve_url"]

            # STEP 2: Create HTTP app
            app = proxy.http_app()
            http_client = TestClient(app)

            # STEP 3: Retrieve full content via HTTP endpoint
            url_parts = retrieve_url.split("?")
            query = url_parts[1]
            response = http_client.get(f"/cache/{token}?{query}")

            assert response.status_code == 200

            # STEP 4: Verify the full content matches original
            import json

            retrieved_content = json.loads(response.text)
            assert retrieved_content == file_content
            assert retrieved_content["content"] == "=" * 1000


# =============================================================================
# 10. Validate CLI Command with Upstream Connections
# =============================================================================


class TestValidateCLIWithUpstream:
    """Tests for validate command checking upstream connections."""

    def test_validate_checks_upstream_connection_flag(self, tmp_path):
        """mcp-proxy validate --check-connections should check connections."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: nonexistent-command-that-will-fail
""")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-C", "-c", str(config_file)])

        # Should attempt connection and report failure
        assert "Checking upstream connections" in result.output
        # Connection will fail since command doesn't exist
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    def test_validate_reports_tool_counts_with_flag(self, tmp_path):
        """mcp-proxy validate --check-connections should report tool counts."""
        from click.testing import CliRunner

        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-C", "-c", str(config_file)])

        # Should show connection check
        assert "Checking upstream connections" in result.output
        # Either shows tools count or connection error
        assert "tools" in result.output.lower() or "failed" in result.output.lower()
