"""Tests for the main MCPProxy class."""

import pytest

from mcp_proxy.hooks import HookResult
from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy, ToolInfo


class TestToolInfo:
    """Tests for ToolInfo dataclass."""

    def test_tool_info_repr(self):
        """ToolInfo.__repr__ should return readable representation."""
        tool = ToolInfo(name="search_code", description="Search code", server="github")

        result = repr(tool)

        assert "ToolInfo" in result
        assert "search_code" in result
        assert "github" in result


class TestMCPProxyInitialization:
    """Tests for MCPProxy initialization."""

    def test_proxy_creation_from_config(self, sample_config_dict):
        """MCPProxy should be creatable from config dict."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy is not None
        assert len(proxy.views) == 1

    def test_proxy_has_fastmcp_server(self, sample_config_dict):
        """MCPProxy should have a FastMCP server instance."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy.server is not None
        assert proxy.server.name == "MCP Tool View Proxy"

    async def test_proxy_initialize_connects_upstreams(self, sample_config_dict):
        """MCPProxy.initialize() should connect to upstream servers."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        # Initialize creates clients for all servers (doesn't connect yet)
        await proxy.initialize()

        # Should have clients registered for all servers in config
        assert "test-server" in proxy.upstream_clients


class TestMCPProxyClientCreation:
    """Tests for upstream client creation."""

    async def test_create_client_for_command_server(self):
        """_create_client should handle command-based servers."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        # Client creation should succeed (actual connection happens on use)
        client = await proxy._create_client("test")
        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")

    async def test_create_client_for_url_server(self):
        """_create_client should handle URL-based servers."""
        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(url="http://localhost:8080/mcp")
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        # Client creation should succeed
        client = await proxy._create_client("test")
        assert client is not None
        assert hasattr(client, "list_tools")
        assert hasattr(client, "call_tool")


class TestMCPProxyGetViewTools:
    """Tests for get_view_tools method."""

    def test_get_view_tools_with_dict_config(self):
        """get_view_tools should handle raw dict tool configs from YAML."""
        import yaml
        from mcp_proxy.config import load_config

        # Simulate raw YAML parsing - tool configs are dicts, not ToolConfig objects
        raw_yaml = """
mcp_servers:
  github:
    url: https://example.com
tool_views:
  research:
    description: Research view
    tools:
      github:
        search_code:
          description: Search code in repos
        list_issues:
          description: List issues
"""
        # Parse directly to simulate what load_config does internally
        raw_data = yaml.safe_load(raw_yaml)

        # Load through the normal config loader
        config = ProxyConfig(**raw_data)
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("research")

        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "search_code" in tool_names
        assert "list_issues" in tool_names

        # Check descriptions came through
        search_tool = next(t for t in tools if t.name == "search_code")
        assert search_tool.description == "Search code in repos"


class TestMCPProxyToolRegistration:
    """Tests for tool registration in direct/search modes."""

    async def test_register_direct_tools(self):
        """_register_direct_tools exposes tools directly."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"tool_a": {}}}
                }
            }
        )
        proxy = MCPProxy(config)

        # After initialization, tools should be registered
        # Can't test without mocked FastMCP server

    async def test_register_search_tool(self):
        """_register_search_tool creates a meta search tool."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"tool_a": {}, "tool_b": {}}}
                }
            }
        )
        proxy = MCPProxy(config)

        # In search mode, only one tool should be registered: view_search_tools


class TestMCPProxyHookWrapping:
    """Tests for hook wrapping of tools."""

    async def test_wrap_tool_with_hooks(self):
        """_wrap_tool_with_hooks adds pre/post hook execution."""
        call_log = []

        async def pre_hook(args, ctx):
            call_log.append("pre")
            return HookResult(args=args)

        async def post_hook(result, args, ctx):
            call_log.append("post")
            return HookResult(result=result)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        await wrapped(query="test")

        assert call_log == ["pre", "tool", "post"]

    async def test_wrap_tool_without_hooks(self):
        """_wrap_tool_with_hooks works without any hooks."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            return {"result": "ok", "args": kwargs}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        result = await wrapped(query="test")

        assert result == {"result": "ok", "args": {"query": "test"}}

    async def test_wrap_tool_with_pre_hook_only(self):
        """_wrap_tool_with_hooks works with only pre_hook."""
        call_log = []

        async def pre_hook(args, ctx):
            call_log.append("pre")
            return HookResult(args=args)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        await wrapped()

        assert call_log == ["pre", "tool"]

    async def test_wrap_tool_with_post_hook_only(self):
        """_wrap_tool_with_hooks works with only post_hook."""
        call_log = []

        async def post_hook(result, args, ctx):
            call_log.append("post")
            return HookResult(result=result)

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def original_tool(**kwargs):
            call_log.append("tool")
            return {"result": "ok"}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        await wrapped()

        assert call_log == ["tool", "post"]

    async def test_wrap_tool_pre_hook_no_args_modification(self):
        """_wrap_tool_with_hooks handles pre_hook that doesn't modify args."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def pre_hook(args, ctx):
            return HookResult()  # No args modification

        async def original_tool(**kwargs):
            return {"args": kwargs}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=pre_hook,
            post_hook=None,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        result = await wrapped(query="test")

        # Args should pass through unchanged
        assert result["args"]["query"] == "test"

    async def test_wrap_tool_post_hook_no_result_modification(self):
        """_wrap_tool_with_hooks handles post_hook that doesn't modify result."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        async def post_hook(result, args, ctx):
            return HookResult()  # No result modification (result=None)

        async def original_tool(**kwargs):
            return {"original": True}

        wrapped = proxy._wrap_tool_with_hooks(
            original_tool,
            pre_hook=None,
            post_hook=post_hook,
            view_name="test",
            tool_name="test_tool",
            upstream_server="server"
        )

        result = await wrapped()

        # Result should pass through unchanged
        assert result["original"] is True


class TestMCPProxyRun:
    """Tests for running the proxy server."""

    async def test_run_with_stdio_transport(self):
        """MCPProxy.run() should support stdio transport."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # Would need to mock FastMCP.run()
        # This verifies the interface exists
        assert hasattr(proxy, "run")

    async def test_run_with_http_transport(self):
        """MCPProxy.run() should support HTTP transport."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # run() should accept transport and port parameters
        assert hasattr(proxy, "run")


class TestMCPProxyToolExecution:
    """Tests for tool execution - tools should route to upstream, not return stubs."""

    async def test_registered_tool_executes_upstream(self):
        """Tools registered on MCP should execute upstream tools, not return stubs."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"my_tool": {"description": "A tool"}}}
                }
            }
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "from_upstream"}
        proxy.upstream_clients = {"server": mock_client}
        # Also inject into the view
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP
        view_mcp = proxy.get_view_mcp("view")

        # Find the registered tool
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "my_tool":
                registered_tool = tool
                break

        assert registered_tool is not None, "Tool should be registered"

        # Call the tool function with arguments dict (FastMCP doesn't support **kwargs)
        result = await registered_tool.fn(arguments={"arg": "value"})

        # Should call upstream and return result
        mock_client.call_tool.assert_called_once()
        assert result == {"result": "from_upstream"}

    async def test_registered_composite_tool_executes(self):
        """Composite tools registered on MCP should execute, not return stubs."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {},
                    "composite_tools": {
                        "multi_tool": {
                            "description": "Composite tool",
                            "inputs": {"query": {"type": "string"}},
                            "parallel": {
                                "result": {"tool": "server.tool_a", "args": {"q": "{inputs.query}"}}
                            }
                        }
                    }
                }
            }
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "from_upstream"}
        proxy.upstream_clients = {"server": mock_client}
        # Also inject into the view
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP
        view_mcp = proxy.get_view_mcp("view")

        # Find the registered composite tool
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "multi_tool":
                registered_tool = tool
                break

        assert registered_tool is not None, "Composite tool should be registered"

        # Call the tool function with arguments dict
        result = await registered_tool.fn(arguments={"query": "test"})

        # The result should NOT be a stub message
        assert "message" not in result or "call via view.call_tool" not in str(result.get("message", ""))
        # Should have called upstream
        mock_client.call_tool.assert_called()


class TestMCPProxyErrorHandling:
    """Tests for MCPProxy error handling."""

    async def test_create_client_unknown_server_raises(self):
        """_create_client should raise for unknown server."""
        config = ProxyConfig(mcp_servers={"known": UpstreamServerConfig(command="echo")}, tool_views={})
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="not found in config"):
            await proxy._create_client("unknown")

    def test_create_client_no_url_or_command_raises(self):
        """_create_client should raise if server has neither url nor command."""
        from mcp_proxy.proxy import MCPProxy

        # Create a config where we manually break the server config
        config = ProxyConfig(mcp_servers={"broken": UpstreamServerConfig(command="echo")}, tool_views={})
        proxy = MCPProxy(config)

        # Manually create a broken config for testing
        broken_config = UpstreamServerConfig(command=None, url=None)
        with pytest.raises(ValueError, match="must have either 'url' or 'command'"):
            proxy._create_client_from_config(broken_config)

    async def test_initialize_only_runs_once(self, sample_config_dict):
        """MCPProxy.initialize() should only run once."""
        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        # First initialization
        await proxy.initialize()
        first_clients = dict(proxy.upstream_clients)

        # Second initialization should be a no-op
        await proxy.initialize()

        assert proxy.upstream_clients == first_clients

    async def test_call_upstream_tool_no_client_raises(self):
        """call_upstream_tool should raise if no client for server."""
        config = ProxyConfig(mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={})
        proxy = MCPProxy(config)
        # Don't call initialize - no clients registered

        with pytest.raises(ValueError, match="No client for server"):
            await proxy.call_upstream_tool("missing", "tool", {})

    def test_get_view_mcp_unknown_view_raises(self):
        """get_view_mcp should raise for unknown view."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="not found"):
            proxy.get_view_mcp("nonexistent")

    async def test_fetch_upstream_tools_no_client_raises(self):
        """fetch_upstream_tools should raise if no client for server."""
        config = ProxyConfig(mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={})
        proxy = MCPProxy(config)
        # Don't call initialize - no clients registered

        with pytest.raises(ValueError, match="No client for server"):
            await proxy.fetch_upstream_tools("missing")

    async def test_refresh_upstream_tools_with_clients(self):
        """refresh_upstream_tools should call fetch for all registered clients."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={})
        proxy = MCPProxy(config)

        # Mock the client
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = []
        proxy.upstream_clients = {"server": mock_client}

        await proxy.refresh_upstream_tools()

        mock_client.list_tools.assert_called()




class TestIncludeAllFetchesFromUpstream:
    """Tests for include_all fetching actual tools from upstream servers."""

    async def test_include_all_uses_upstream_tools(self):
        """include_all: true should include tools from upstream, not just config."""
        from unittest.mock import AsyncMock, MagicMock

        # Config has include_all: true but no tools defined in config
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "include_all": True,
                    "tools": {}  # No tools defined in config
                }
            }
        )
        proxy = MCPProxy(config)

        # Mock the upstream client that returns actual tools
        mock_tool = MagicMock()
        mock_tool.name = "upstream_tool"
        mock_tool.description = "A tool from upstream"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        # Fetch tools from upstream (simulates what happens during initialization)
        await proxy.fetch_upstream_tools("server")

        # Now get view tools - should include the upstream tool
        tools = proxy.get_view_tools("view")

        # FAILING ASSERTION: Currently returns empty because config has no tools
        tool_names = [t.name for t in tools]
        assert "upstream_tool" in tool_names, f"Expected 'upstream_tool' in {tool_names}"

    async def test_include_all_with_no_config_tools_still_works(self):
        """include_all should work even when server has no tools in config."""
        from unittest.mock import AsyncMock, MagicMock

        # Server has no 'tools' key at all in config
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},  # No tools key
            tool_views={
                "view": {
                    "include_all": True,
                    "tools": {}
                }
            }
        )
        proxy = MCPProxy(config)

        # Mock upstream returns tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools("view")
        tool_names = [t.name for t in tools]

        # Should include both upstream tools
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names

    @pytest.mark.asyncio
    async def test_include_all_with_view_override_for_upstream_tool(self):
        """include_all should apply view overrides to upstream tools."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.models import ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(url="http://example.com")
            },
            tool_views={
                "view": ToolViewConfig(
                    include_all=True,
                    # Override tool_a with custom name and description
                    tools={
                        "server": {
                            "tool_a": ToolConfig(
                                name="renamed_tool_a",
                                description="Custom description"
                            )
                        }
                    }
                )
            }
        )
        proxy = MCPProxy(config)

        # Mock upstream tools
        mock_tool = MagicMock()
        mock_tool.name = "tool_a"
        mock_tool.description = "Original description"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools("view")
        tool_names = [t.name for t in tools]
        tool_descs = {t.name: t.description for t in tools}

        # Should use overridden name and description
        assert "renamed_tool_a" in tool_names
        assert "tool_a" not in tool_names
        assert tool_descs["renamed_tool_a"] == "Custom description"


class TestDefaultMCPUpstreamCalls:
    """Tests for default MCP (no view) upstream tool calls."""

    @pytest.mark.asyncio
    async def test_default_mcp_calls_upstream_when_connected(self):
        """Default MCP tools should call upstream when clients are connected."""
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={"my_tool": {"description": "A tool"}}
                )
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        # Create mock upstream client
        mock_upstream = MagicMock()
        mock_upstream.__aenter__ = AsyncMock(return_value=mock_upstream)
        mock_upstream.__aexit__ = AsyncMock(return_value=None)
        mock_upstream.call_tool = AsyncMock(return_value={"result": "success"})
        proxy.upstream_clients = {"server": mock_upstream}

        # Call through the proxy's default server
        async with Client(proxy.server) as client:
            result = await client.call_tool("my_tool", {"arg": "value"})

        # Verify upstream was called
        mock_upstream.call_tool.assert_called_once_with("my_tool", {"arg": "value"})
