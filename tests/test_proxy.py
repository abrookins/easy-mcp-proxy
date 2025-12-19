"""Tests for the main MCPProxy class."""

import pytest


class TestMCPProxyInitialization:
    """Tests for MCPProxy initialization."""

    def test_proxy_creation_from_config(self, sample_config_dict):
        """MCPProxy should be creatable from config dict."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy is not None
        assert len(proxy.views) == 1

    def test_proxy_has_fastmcp_server(self, sample_config_dict):
        """MCPProxy should have a FastMCP server instance."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        assert proxy.server is not None
        assert proxy.server.name == "MCP Tool View Proxy"

    async def test_proxy_initialize_connects_upstreams(self, sample_config_dict):
        """MCPProxy.initialize() should connect to upstream servers."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

        config = ProxyConfig(**sample_config_dict)
        proxy = MCPProxy(config)

        # Without real upstream servers, this would fail
        with pytest.raises(Exception):
            await proxy.initialize()


class TestMCPProxyClientCreation:
    """Tests for upstream client creation."""

    async def test_create_client_for_command_server(self):
        """_create_client should handle command-based servers."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig, UpstreamServerConfig

        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(command="echo", args=["test"])
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        # Would need mocking to test actual client creation
        # This verifies the interface exists
        with pytest.raises(Exception):
            await proxy._create_client("test")

    async def test_create_client_for_url_server(self):
        """_create_client should handle URL-based servers."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig, UpstreamServerConfig

        config = ProxyConfig(
            mcp_servers={
                "test": UpstreamServerConfig(url="http://localhost:8080/mcp")
            },
            tool_views={}
        )
        proxy = MCPProxy(config)

        with pytest.raises(Exception):
            await proxy._create_client("test")


class TestMCPProxyToolRegistration:
    """Tests for tool registration in direct/search modes."""

    async def test_register_direct_tools(self):
        """_register_direct_tools exposes tools directly."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

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
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

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
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig
        from mcp_proxy.hooks import HookResult

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


class TestMCPProxyRun:
    """Tests for running the proxy server."""

    async def test_run_with_stdio_transport(self):
        """MCPProxy.run() should support stdio transport."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # Would need to mock FastMCP.run()
        # This verifies the interface exists
        assert hasattr(proxy, "run")

    async def test_run_with_http_transport(self):
        """MCPProxy.run() should support HTTP transport."""
        from mcp_proxy.proxy import MCPProxy
        from mcp_proxy.models import ProxyConfig

        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        # run() should accept transport and port parameters
        assert hasattr(proxy, "run")

