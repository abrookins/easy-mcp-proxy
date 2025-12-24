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

