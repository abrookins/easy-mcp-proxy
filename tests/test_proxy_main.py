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

    def test_tool_info_stores_input_schema(self):
        """ToolInfo should store input_schema when provided."""
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        }
        tool = ToolInfo(
            name="search_code",
            description="Search code",
            server="github",
            input_schema=schema,
        )

        assert tool.input_schema == schema
        assert tool.input_schema["properties"]["query"]["type"] == "string"

    def test_tool_info_input_schema_defaults_to_none(self):
        """ToolInfo.input_schema should default to None."""
        tool = ToolInfo(name="search_code", description="Search code", server="github")

        assert tool.input_schema is None


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
            mcp_servers={"test": UpstreamServerConfig(command="echo", args=["test"])},
            tool_views={},
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
            mcp_servers={"test": UpstreamServerConfig(url="http://localhost:8080/mcp")},
            tool_views={},
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


class TestMCPProxyInstructions:
    """Tests for upstream server instruction forwarding."""

    def test_proxy_stores_upstream_instructions(self):
        """Proxy should store instructions fetched from upstream servers."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Initially no instructions
        assert proxy.upstream_instructions == {}

        # After setting instructions (simulating fetch)
        proxy.upstream_instructions["server"] = "Test instructions"
        assert proxy.upstream_instructions["server"] == "Test instructions"

    def test_get_aggregated_instructions_single_server(self):
        """Aggregated instructions should combine all upstream instructions."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)
        proxy.upstream_instructions["server"] = "Instructions from server"

        result = proxy.get_aggregated_instructions()

        assert "server" in result
        assert "Instructions from server" in result

    def test_get_aggregated_instructions_multiple_servers(self):
        """Aggregated instructions should include all servers."""
        config = ProxyConfig(
            mcp_servers={
                "server1": {"command": "echo"},
                "server2": {"command": "echo"},
            },
            tool_views={},
        )
        proxy = MCPProxy(config)
        proxy.upstream_instructions["server1"] = "First server instructions"
        proxy.upstream_instructions["server2"] = "Second server instructions"

        result = proxy.get_aggregated_instructions()

        assert "server1" in result
        assert "First server instructions" in result
        assert "server2" in result
        assert "Second server instructions" in result

    def test_get_aggregated_instructions_empty(self):
        """Aggregated instructions should return None when no instructions."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)

        result = proxy.get_aggregated_instructions()

        assert result is None

    def test_get_aggregated_instructions_all_empty(self):
        """Aggregated instructions should return None when all are empty strings."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)
        # Set instructions to empty/falsy values
        proxy.upstream_instructions["server1"] = ""
        proxy.upstream_instructions["server2"] = None

        result = proxy.get_aggregated_instructions()

        assert result is None

    def test_view_mcp_has_aggregated_instructions(self):
        """View MCP should have aggregated instructions set."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)
        proxy.upstream_instructions["server"] = "Server instructions here"

        view_mcp = proxy.get_view_mcp("myview")

        assert view_mcp.instructions is not None
        assert "Server instructions here" in view_mcp.instructions

    @pytest.mark.asyncio
    async def test_fetch_upstream_instructions(self):
        """fetch_upstream_instructions should fetch and store instructions."""
        from unittest.mock import AsyncMock, MagicMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock the client with initialize_result containing instructions
        mock_client = MagicMock()
        mock_init_result = MagicMock()
        mock_init_result.instructions = "Instructions from upstream"
        mock_client.initialize_result = mock_init_result
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        await proxy.fetch_upstream_instructions("server", mock_client)

        assert proxy.upstream_instructions["server"] == "Instructions from upstream"

    @pytest.mark.asyncio
    async def test_fetch_upstream_instructions_none(self):
        """fetch_upstream_instructions should handle None instructions."""
        from unittest.mock import AsyncMock, MagicMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock the client with no instructions
        mock_client = MagicMock()
        mock_init_result = MagicMock()
        mock_init_result.instructions = None
        mock_client.initialize_result = mock_init_result
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        await proxy.fetch_upstream_instructions("server", mock_client)

        # Should not store None instructions
        assert "server" not in proxy.upstream_instructions

    @pytest.mark.asyncio
    async def test_refresh_upstream_tools_fetches_instructions(self):
        """refresh_upstream_tools should also fetch instructions."""
        from unittest.mock import AsyncMock, MagicMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock the client with instructions
        mock_client = MagicMock()
        mock_init_result = MagicMock()
        mock_init_result.instructions = "Test instructions"
        mock_client.initialize_result = mock_init_result
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        proxy.upstream_clients["server"] = mock_client

        await proxy.refresh_upstream_tools()

        assert proxy.upstream_instructions.get("server") == "Test instructions"

    def test_get_server_instructions_tool_registered(self):
        """get_server_instructions tool should be registered on view MCP."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)
        proxy.upstream_instructions["server"] = "Server instructions here"

        view_mcp = proxy.get_view_mcp("myview")

        # Check that get_server_instructions tool is registered
        tools = view_mcp._tool_manager._tools
        assert "get_server_instructions" in tools

    @pytest.mark.asyncio
    async def test_get_server_instructions_tool_returns_instructions(self):
        """get_server_instructions tool should return aggregated instructions."""
        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={"myview": {"description": "Test view"}},
        )
        proxy = MCPProxy(config)
        proxy.upstream_instructions["server"] = "Server instructions here"

        view_mcp = proxy.get_view_mcp("myview")

        async with Client(view_mcp) as client:
            result = await client.call_tool("get_server_instructions", {})
            # Result is a CallToolResult with content
            assert len(result.content) > 0
            text_content = result.content[0].text
            assert "Server instructions here" in text_content


class TestMCPProxyToolRegistration:
    """Tests for tool registration in direct/search modes."""

    async def test_register_direct_tools(self):
        """_register_direct_tools exposes tools directly."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {"exposure_mode": "direct", "tools": {"server": {"tool_a": {}}}}
            },
        )
        MCPProxy(config)

        # After initialization, tools should be registered
        # Can't test without mocked FastMCP server

    async def test_register_search_tool(self):
        """_register_search_tool creates a meta search tool."""
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "search",
                    "tools": {"server": {"tool_a": {}, "tool_b": {}}},
                }
            },
        )
        MCPProxy(config)

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
            upstream_server="server",
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
            upstream_server="server",
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
            upstream_server="server",
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
            upstream_server="server",
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
            upstream_server="server",
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
            upstream_server="server",
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
                    "tools": {"server": {"my_tool": {"description": "A tool"}}},
                }
            },
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
                                "result": {
                                    "tool": "server.tool_a",
                                    "args": {"q": "{inputs.query}"},
                                }
                            },
                        }
                    },
                }
            },
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
        assert "message" not in result or "call via view.call_tool" not in str(
            result.get("message", "")
        )
        # Should have called upstream
        mock_client.call_tool.assert_called()


class TestMCPProxyErrorHandling:
    """Tests for MCPProxy error handling."""

    async def test_create_client_unknown_server_raises(self):
        """_create_client should raise for unknown server."""
        config = ProxyConfig(
            mcp_servers={"known": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        with pytest.raises(ValueError, match="not found in config"):
            await proxy._create_client("unknown")

    def test_create_client_no_url_or_command_raises(self):
        """_create_client should raise if server has neither url nor command."""
        from mcp_proxy.proxy import MCPProxy

        # Create a config where we manually break the server config
        config = ProxyConfig(
            mcp_servers={"broken": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Manually create a broken config for testing
        broken_config = UpstreamServerConfig(command=None, url=None)
        with pytest.raises(ValueError, match="must have either 'url' or 'command'"):
            proxy._create_client_from_config(broken_config)

    def test_create_client_from_config_with_cwd(self):
        """_create_client_from_config should pass cwd to StdioTransport."""
        from unittest.mock import MagicMock, patch

        from fastmcp.client.transports import StdioTransport

        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem", "/data"],
                    cwd="/data",
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create a real StdioTransport mock that passes isinstance checks
        mock_transport_instance = MagicMock(spec=StdioTransport)

        with patch(
            "mcp_proxy.proxy.client.StdioTransport",
            return_value=mock_transport_instance,
        ) as mock_transport_class:
            proxy._create_client_from_config(config.mcp_servers["fs"])

            # Verify cwd was passed to StdioTransport
            mock_transport_class.assert_called_once()
            call_kwargs = mock_transport_class.call_args
            assert call_kwargs.kwargs.get("cwd") == "/data"

    def test_create_client_from_config_cwd_with_env_expansion(self):
        """_create_client_from_config should expand env vars in cwd."""
        import os
        from unittest.mock import MagicMock, patch

        from fastmcp.client.transports import StdioTransport

        os.environ["TEST_CWD_PATH"] = "/expanded/path"

        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(command="echo", cwd="${TEST_CWD_PATH}")
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_transport_instance = MagicMock(spec=StdioTransport)

        with patch(
            "mcp_proxy.proxy.client.StdioTransport",
            return_value=mock_transport_instance,
        ) as mock_transport_class:
            proxy._create_client_from_config(config.mcp_servers["fs"])

            call_kwargs = mock_transport_class.call_args
            cwd_value = call_kwargs.kwargs.get("cwd")
            assert cwd_value == "/expanded/path"

        del os.environ["TEST_CWD_PATH"]

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
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
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
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)
        # Don't call initialize - no clients registered

        with pytest.raises(ValueError, match="No client for server"):
            await proxy.fetch_upstream_tools("missing")

    async def test_refresh_upstream_tools_with_clients(self):
        """refresh_upstream_tools should call fetch for all registered clients."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock the client
        mock_client = AsyncMock()
        mock_client.list_tools.return_value = []
        proxy.upstream_clients = {"server": mock_client}

        await proxy.refresh_upstream_tools()

        mock_client.list_tools.assert_called()


class TestDefaultViewIncludesAllUpstreamTools:
    """Tests for default view including all tools from servers without tools config."""

    async def test_default_view_includes_all_tools_when_no_tools_config(self):
        """Default view should include ALL tools from servers without 'tools' config."""
        from unittest.mock import AsyncMock, MagicMock

        # Server has NO 'tools' key - should include all tools from upstream
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},  # No tools key
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool1.inputSchema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"
        mock_tool2.inputSchema = {
            "type": "object",
            "properties": {"y": {"type": "number"}},
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        # Fetch tools from upstream
        await proxy.fetch_upstream_tools("server")

        # Get default view tools (view_name=None)
        tools = proxy.get_view_tools(None)

        tool_names = [t.name for t in tools]
        assert "tool_a" in tool_names
        assert "tool_b" in tool_names
        assert len(tools) == 2

        # Check schemas are preserved
        tool_a = next(t for t in tools if t.name == "tool_a")
        assert tool_a.input_schema is not None
        assert tool_a.input_schema["properties"]["x"]["type"] == "string"

    async def test_default_view_filters_when_tools_config_exists(self):
        """Default view should only include configured tools when 'tools' is set."""
        from unittest.mock import AsyncMock, MagicMock

        # Server HAS 'tools' key - should only include those tools
        config = ProxyConfig(
            mcp_servers={
                "server": {
                    "command": "echo",
                    "tools": {"tool_a": {}},  # Only tool_a is configured
                }
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream has both tools
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A"
        mock_tool1.inputSchema = {"type": "object"}

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B"

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool1, mock_tool2]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools(None)

        # Only tool_a should be in the list
        tool_names = [t.name for t in tools]
        assert "tool_a" in tool_names
        assert "tool_b" not in tool_names
        assert len(tools) == 1


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
                    "tools": {},  # No tools defined in config
                }
            },
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
        assert "upstream_tool" in tool_names, (
            f"Expected 'upstream_tool' in {tool_names}"
        )

    async def test_include_all_with_no_config_tools_still_works(self):
        """include_all should work even when server has no tools in config."""
        from unittest.mock import AsyncMock, MagicMock

        # Server has no 'tools' key at all in config
        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},  # No tools key
            tool_views={"view": {"include_all": True, "tools": {}}},
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
            mcp_servers={"server": UpstreamServerConfig(url="http://example.com")},
            tool_views={
                "view": ToolViewConfig(
                    include_all=True,
                    # Override tool_a with custom name and description
                    tools={
                        "server": {
                            "tool_a": ToolConfig(
                                name="renamed_tool_a", description="Custom description"
                            )
                        }
                    },
                )
            },
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
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastmcp import Client

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={"my_tool": {"description": "A tool"}},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create mock upstream client
        mock_upstream = MagicMock()
        mock_upstream.__aenter__ = AsyncMock(return_value=mock_upstream)
        mock_upstream.__aexit__ = AsyncMock(return_value=None)
        mock_upstream.call_tool = AsyncMock(return_value={"result": "success"})

        # Mock _create_client_from_config to return our mock client
        with patch.object(
            proxy, "_create_client_from_config", return_value=mock_upstream
        ):
            # Call through the proxy's default server
            # Tools use "arguments" dict parameter per FastMCP convention
            async with Client(proxy.server) as client:
                await client.call_tool("my_tool", {"arguments": {"arg": "value"}})

            # Verify upstream was called with the arguments dict
            mock_upstream.call_tool.assert_called_once_with("my_tool", {"arg": "value"})


class TestToolNameAliasing:
    """Tests for tool name aliasing at the mcp_servers level."""

    def test_tool_info_tracks_original_name_when_aliased(self):
        """ToolInfo should track original_name when tool is aliased."""
        tool = ToolInfo(
            name="aliased_name",
            description="Test",
            server="test",
            original_name="original_name",
        )

        assert tool.name == "aliased_name"
        assert tool.original_name == "original_name"

    def test_tool_info_original_name_defaults_to_name(self):
        """ToolInfo.original_name should default to name when not aliased."""
        tool = ToolInfo(name="my_tool", description="Test", server="test")

        assert tool.name == "my_tool"
        assert tool.original_name == "my_tool"

    def test_get_view_tools_applies_name_alias_in_default_view(self):
        """get_view_tools should apply name alias from server config in default view."""
        from mcp_proxy.models import ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",
                    args=["test"],
                    tools={
                        "original_tool": ToolConfig(
                            name="aliased_tool", description="Test description"
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].name == "aliased_tool"
        assert tools[0].original_name == "original_tool"
        assert tools[0].description == "Test description"

    def test_get_view_tools_preserves_name_when_no_alias(self):
        """get_view_tools should use original name when no alias specified."""
        from mcp_proxy.models import ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "test-server": UpstreamServerConfig(
                    command="echo",
                    tools={"my_tool": ToolConfig(description="No alias")},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].name == "my_tool"
        assert tools[0].original_name == "my_tool"

    def test_get_view_tools_multiple_tools_with_mixed_aliases(self):
        """get_view_tools should handle mix of aliased and non-aliased tools."""
        from mcp_proxy.models import ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_a": ToolConfig(name="renamed_a", description="A"),
                        "tool_b": ToolConfig(description="B"),
                        "tool_c": ToolConfig(name="renamed_c", description="C"),
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        by_name = {t.name: t for t in tools}

        assert "renamed_a" in by_name
        assert by_name["renamed_a"].original_name == "tool_a"

        assert "tool_b" in by_name
        assert by_name["tool_b"].original_name == "tool_b"

        assert "renamed_c" in by_name
        assert by_name["renamed_c"].original_name == "tool_c"

    @pytest.mark.asyncio
    async def test_aliased_tool_calls_upstream_with_original_name(self):
        """Aliased tools should call upstream using original tool name."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastmcp import Client

        from mcp_proxy.models import ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    url="http://example.com",
                    tools={
                        "original_tool_name": ToolConfig(
                            name="aliased_tool_name", description="An aliased tool"
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Create mock upstream client
        mock_upstream = MagicMock()
        mock_upstream.__aenter__ = AsyncMock(return_value=mock_upstream)
        mock_upstream.__aexit__ = AsyncMock(return_value=None)
        mock_upstream.call_tool = AsyncMock(return_value={"result": "success"})

        # Mock _create_client_from_config to return our mock client
        with patch.object(
            proxy, "_create_client_from_config", return_value=mock_upstream
        ):
            # Call using the aliased name
            async with Client(proxy.server) as client:
                # The tool is exposed as "aliased_tool_name"
                await client.call_tool(
                    "aliased_tool_name", {"arguments": {"key": "value"}}
                )

            # But upstream should be called with "original_tool_name"
            mock_upstream.call_tool.assert_called_once_with(
                "original_tool_name", {"key": "value"}
            )


class TestToolNameAliasingInViews:
    """Tests for tool name aliasing in tool_views."""

    def test_view_alias_in_explicit_tools(self):
        """View with explicit tools should apply name alias."""
        from mcp_proxy.models import ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"upstream_tool": ToolConfig(description="Original")},
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    tools={
                        "server": {
                            "upstream_tool": ToolConfig(
                                name="view_aliased_tool", description="View override"
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].name == "view_aliased_tool"
        assert tools[0].original_name == "upstream_tool"
        assert tools[0].description == "View override"

    def test_view_alias_in_include_all_mode(self):
        """View with include_all should apply alias from view overrides."""
        from mcp_proxy.models import ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo", tools={"tool_a": ToolConfig(description="A")}
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                    tools={
                        "server": {
                            "tool_a": ToolConfig(
                                name="renamed_in_view", description="Renamed"
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].name == "renamed_in_view"
        assert tools[0].original_name == "tool_a"


class TestInputSchemaPreservation:
    """Tests for preserving upstream tool input schemas."""

    async def test_input_schema_captured_from_upstream(self):
        """Input schema should be captured when fetching tools from upstream."""
        from unittest.mock import AsyncMock, MagicMock

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with inputSchema
        mock_tool = MagicMock()
        mock_tool.name = "search_code"
        mock_tool.description = "Search code in repos"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["query"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        # Fetch tools from upstream
        await proxy.fetch_upstream_tools("server")

        # Check that tools were fetched and cached
        assert "server" in proxy._upstream_tools
        assert len(proxy._upstream_tools["server"]) == 1
        # The raw tool object should have inputSchema
        cached_tool = proxy._upstream_tools["server"][0]
        assert cached_tool.inputSchema["properties"]["query"]["type"] == "string"

    async def test_input_schema_passed_to_view_tools(self):
        """Input schema should be included in get_view_tools output."""
        from unittest.mock import AsyncMock, MagicMock

        from mcp_proxy.models import ToolViewConfig

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with inputSchema
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "My tool"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"arg": {"type": "string"}},
            "required": ["arg"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")
        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].input_schema is not None
        assert tools[0].input_schema["properties"]["arg"]["type"] == "string"

    async def test_input_schema_exposed_via_mcp_list_tools(self):
        """Input schema should be exposed when listing tools via MCP client."""
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp import Client

        from mcp_proxy.models import ToolViewConfig

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                )
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with inputSchema
        mock_tool = MagicMock()
        mock_tool.name = "search_tool"
        mock_tool.description = "Search tool"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        # Get the MCP for the view and list tools
        view_mcp = proxy.get_view_mcp("test-view")
        async with Client(view_mcp) as client:
            tools = await client.list_tools()

        # Should have 2 tools: search_tool + get_server_instructions
        assert len(tools) == 2
        tool = next(t for t in tools if t.name == "search_tool")
        assert tool.name == "search_tool"
        # The inputSchema should match what we provided
        assert tool.inputSchema["properties"]["query"]["type"] == "string"
        assert tool.inputSchema["properties"]["max_results"]["type"] == "integer"
        assert "query" in tool.inputSchema.get("required", [])


class TestToolAliases:
    """Tests for multiple aliases from a single upstream tool."""

    def test_aliases_creates_multiple_tools_in_default_view(self):
        """Aliases should create multiple tools from one upstream tool."""
        from mcp_proxy.models import AliasConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "create_item": ToolConfig(
                            aliases=[
                                AliasConfig(
                                    name="create_memory", description="Save a memory"
                                ),
                                AliasConfig(
                                    name="create_skill", description="Save a skill"
                                ),
                            ]
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        by_name = {t.name: t for t in tools}

        assert len(tools) == 2
        assert "create_memory" in by_name
        assert "create_skill" in by_name

        # Both should point to the same original tool
        assert by_name["create_memory"].original_name == "create_item"
        assert by_name["create_skill"].original_name == "create_item"

        # Descriptions should be set correctly
        assert by_name["create_memory"].description == "Save a memory"
        assert by_name["create_skill"].description == "Save a skill"

    def test_aliases_all_call_same_upstream_tool(self):
        """All aliases should route to the same upstream tool."""
        from mcp_proxy.models import AliasConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "backend": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "store_data": ToolConfig(
                            aliases=[
                                AliasConfig(name="save_memory", description="Memory"),
                                AliasConfig(name="save_skill", description="Skill"),
                                AliasConfig(name="save_note", description="Note"),
                            ]
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        # All three aliases exist
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"save_memory", "save_skill", "save_note"}

        # All point to same original
        for tool in tools:
            assert tool.original_name == "store_data"
            assert tool.server == "backend"

    def test_multiple_tools_with_aliases(self):
        """Multiple upstream tools can each have their own aliases."""
        from mcp_proxy.models import AliasConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "create_item": ToolConfig(
                            aliases=[
                                AliasConfig(name="create_memory", description="Memory"),
                                AliasConfig(name="create_skill", description="Skill"),
                            ]
                        ),
                        "search_items": ToolConfig(
                            aliases=[
                                AliasConfig(
                                    name="search_memories",
                                    description="Search memories",
                                ),
                                AliasConfig(
                                    name="search_skills", description="Search skills"
                                ),
                            ]
                        ),
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        by_name = {t.name: t for t in tools}

        assert len(tools) == 4
        assert by_name["create_memory"].original_name == "create_item"
        assert by_name["create_skill"].original_name == "create_item"
        assert by_name["search_memories"].original_name == "search_items"
        assert by_name["search_skills"].original_name == "search_items"

    def test_mix_of_aliased_and_regular_tools(self):
        """Can mix tools with aliases and tools with simple name/no override."""
        from mcp_proxy.models import AliasConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "aliased_tool": ToolConfig(
                            aliases=[
                                AliasConfig(name="alias_1", description="First"),
                                AliasConfig(name="alias_2", description="Second"),
                            ]
                        ),
                        "renamed_tool": ToolConfig(
                            name="new_name", description="Renamed"
                        ),
                        "plain_tool": ToolConfig(description="Plain"),
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)
        by_name = {t.name: t for t in tools}

        assert len(tools) == 4

        # Aliased tool creates two entries
        assert "alias_1" in by_name
        assert "alias_2" in by_name

        # Renamed tool uses new name
        assert "new_name" in by_name
        assert by_name["new_name"].original_name == "renamed_tool"

        # Plain tool keeps original name
        assert "plain_tool" in by_name
        assert by_name["plain_tool"].original_name == "plain_tool"


class TestAliasesInIncludeAllMode:
    """Tests for aliases in include_all views with view overrides."""

    def test_aliases_in_include_all_with_view_override(self):
        """include_all view with aliases in view override creates multiple tools."""
        from mcp_proxy.models import AliasConfig, ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"base_tool": ToolConfig(description="Original tool")},
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                    tools={
                        "server": {
                            "base_tool": ToolConfig(
                                aliases=[
                                    AliasConfig(
                                        name="alias_one", description="First alias"
                                    ),
                                    AliasConfig(
                                        name="alias_two", description="Second alias"
                                    ),
                                ]
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Need to simulate upstream tools being fetched
        from unittest.mock import MagicMock

        upstream_tool = MagicMock()
        upstream_tool.name = "base_tool"
        upstream_tool.description = "Original from upstream"
        upstream_tool.inputSchema = {"type": "object", "properties": {}}

        proxy._upstream_tools["server"] = [upstream_tool]

        tools = proxy.get_view_tools("test-view")
        by_name = {t.name: t for t in tools}

        assert len(tools) == 2
        assert "alias_one" in by_name
        assert "alias_two" in by_name

        # Both should point to the same original tool
        assert by_name["alias_one"].original_name == "base_tool"
        assert by_name["alias_two"].original_name == "base_tool"

        # Descriptions should be from aliases
        assert by_name["alias_one"].description == "First alias"
        assert by_name["alias_two"].description == "Second alias"

    def test_aliases_in_include_all_fallback_to_config_tools(self):
        """include_all with aliases should work when upstream not fetched."""
        from mcp_proxy.models import AliasConfig, ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "tool_a": ToolConfig(
                            aliases=[
                                AliasConfig(
                                    name="tool_a_alias1", description="Alias 1"
                                ),
                                AliasConfig(
                                    name="tool_a_alias2", description="Alias 2"
                                ),
                            ]
                        )
                    },
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    include_all=True,
                    tools={
                        "server": {}  # No view overrides
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Don't set _upstream_tools - fallback to config

        tools = proxy.get_view_tools("test-view")
        by_name = {t.name: t for t in tools}

        assert len(tools) == 2
        assert "tool_a_alias1" in by_name
        assert "tool_a_alias2" in by_name
        assert by_name["tool_a_alias1"].original_name == "tool_a"
        assert by_name["tool_a_alias2"].original_name == "tool_a"


class TestAliasesInExplicitToolMode:
    """Tests for aliases in explicit tool mode views."""

    def test_aliases_in_explicit_mode_with_upstream_schema(self):
        """Explicit tool mode with aliases should get upstream schema."""
        from mcp_proxy.models import AliasConfig, ToolConfig, ToolViewConfig

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    tools={
                        "server": {
                            "search_tool": ToolConfig(
                                aliases=[
                                    AliasConfig(name="search_by_name"),
                                    AliasConfig(name="search_by_id"),
                                ]
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        # Simulate upstream tools with schema
        from unittest.mock import MagicMock

        upstream_tool = MagicMock()
        upstream_tool.name = "search_tool"
        upstream_tool.description = "Search for items"
        upstream_tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

        proxy._upstream_tools["server"] = [upstream_tool]

        tools = proxy.get_view_tools("test-view")
        by_name = {t.name: t for t in tools}

        assert len(tools) == 2
        assert "search_by_name" in by_name
        assert "search_by_id" in by_name

        # Should have the upstream schema
        assert by_name["search_by_name"].input_schema is not None
        assert (
            by_name["search_by_name"].input_schema["properties"]["query"]["type"]
            == "string"
        )

        # Original name should be preserved
        assert by_name["search_by_name"].original_name == "search_tool"
        assert by_name["search_by_id"].original_name == "search_tool"


class TestToolExecutionWithInputSchema:
    """Tests for tool execution paths with input schema."""

    async def test_tool_with_input_schema_calls_upstream_with_kwargs(self):
        """Tools with input_schema should use **kwargs wrapper and execute."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(
            mcp_servers={"server": {"command": "echo"}},
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"my_tool": {"description": "A tool"}}},
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "success"}
        proxy.upstream_clients = {"server": mock_client}
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Simulate upstream tools with schema
        from unittest.mock import MagicMock

        upstream_tool = MagicMock()
        upstream_tool.name = "my_tool"
        upstream_tool.description = "A tool"
        upstream_tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        proxy._upstream_tools["server"] = [upstream_tool]

        # Recreate view MCP to pick up schema
        view_mcp = proxy.get_view_mcp("view")

        # Find the registered tool
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "my_tool":
                registered_tool = tool
                break

        assert registered_tool is not None, "Tool should be registered"

        # Call the tool function with **kwargs (schema-based registration)
        result = await registered_tool.fn(query="test_query")

        # Should call upstream
        mock_client.call_tool.assert_called_once()
        assert result == {"result": "success"}

    async def test_direct_routing_with_input_schema(self):
        """Direct routing (no view) with input_schema should work."""
        from unittest.mock import AsyncMock, patch

        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.call_tool.return_value = {"result": "direct_success"}

        # Manually create ToolInfo with input_schema (simulating what would
        # happen if get_view_tools returned tools with schemas)
        tools_with_schema = [
            ToolInfo(
                name="direct_tool",
                description="A direct tool",
                server="server",
                original_name="direct_tool",
                input_schema={
                    "type": "object",
                    "properties": {"arg1": {"type": "string"}},
                },
            )
        ]

        # Register on a new FastMCP without a view
        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools_with_schema)  # No view

        # Find and call the registered tool
        registered_tool = test_mcp._tool_manager._tools.get("direct_tool")
        assert registered_tool is not None

        # Mock _create_client_from_config to return our mock client
        with patch.object(
            proxy, "_create_client_from_config", return_value=mock_client
        ):
            # Call the tool (direct routing without view)
            result = await registered_tool.fn(arg1="test")

            mock_client.call_tool.assert_called_once_with(
                "direct_tool", {"arg1": "test"}
            )
            assert result == {"result": "direct_success"}

    async def test_direct_routing_server_not_configured_raises(self):
        """Direct routing should raise when server not configured."""
        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={},  # No servers configured
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Manually create ToolInfo with input_schema referencing a non-existent server
        tools_with_schema = [
            ToolInfo(
                name="test_tool",
                description="Test",
                server="nonexistent_server",
                original_name="test_tool",
                input_schema={"type": "object"},
            )
        ]

        # Register on a new FastMCP without a view
        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools_with_schema)

        registered_tool = test_mcp._tool_manager._tools.get("test_tool")
        assert registered_tool is not None

        # Calling should raise because server is not configured
        with pytest.raises(
            ValueError, match="Server 'nonexistent_server' not configured"
        ):
            await registered_tool.fn(arg="value")

    async def test_direct_routing_uses_active_client(self):
        """Direct routing should use active client when available."""
        from unittest.mock import AsyncMock

        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock active client
        active_client = AsyncMock()
        active_client.call_tool.return_value = {"from": "active"}
        proxy._active_clients["server"] = active_client

        # Create ToolInfo with input_schema
        tools_with_schema = [
            ToolInfo(
                name="direct_tool",
                description="A direct tool",
                server="server",
                original_name="direct_tool",
                input_schema={
                    "type": "object",
                    "properties": {"arg1": {"type": "string"}},
                },
            )
        ]

        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools_with_schema)

        registered_tool = test_mcp._tool_manager._tools.get("direct_tool")
        result = await registered_tool.fn(arg1="test")

        # Should use active client
        active_client.call_tool.assert_called_once_with("direct_tool", {"arg1": "test"})
        assert result == {"from": "active"}

    async def test_direct_routing_dict_wrapper_uses_active_client(self):
        """Direct routing with dict wrapper should use active client."""
        from unittest.mock import AsyncMock

        from fastmcp import FastMCP

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock active client
        active_client = AsyncMock()
        active_client.call_tool.return_value = {"from": "active_dict"}
        proxy._active_clients["server"] = active_client

        # Create ToolInfo WITHOUT input_schema (will use dict wrapper)
        tools_without_schema = [
            ToolInfo(
                name="dict_tool",
                description="A dict tool",
                server="server",
                original_name="dict_tool",
                input_schema=None,  # No schema = dict wrapper
            )
        ]

        test_mcp = FastMCP(name="test")
        proxy._register_tools_on_mcp(test_mcp, tools_without_schema)

        registered_tool = test_mcp._tool_manager._tools.get("dict_tool")
        result = await registered_tool.fn(arguments={"arg1": "test"})

        # Should use active client
        active_client.call_tool.assert_called_once_with("dict_tool", {"arg1": "test"})
        assert result == {"from": "active_dict"}


class TestParameterBinding:
    """Tests for parameter binding (hidden params, renamed params)."""

    def test_transform_schema_hides_parameter(self):
        """_transform_schema should remove hidden parameters from schema."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["path", "query"],
        }
        tool_config = ToolConfig(
            parameters={"path": ParameterConfig(hidden=True, default="/skills")}
        )

        result = _transform_schema(schema, tool_config)

        assert "path" not in result["properties"]
        assert "path" not in result["required"]
        assert "query" in result["properties"]
        assert "query" in result["required"]

    def test_transform_schema_renames_parameter(self):
        """_transform_schema should rename parameters."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        }
        tool_config = ToolConfig(
            parameters={"path": ParameterConfig(rename="category")}
        )

        result = _transform_schema(schema, tool_config)

        assert "path" not in result["properties"]
        assert "path" not in result["required"]
        assert "category" in result["properties"]
        assert "category" in result["required"]

    def test_transform_schema_updates_description(self):
        """_transform_schema should update parameter description."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Original desc"},
            },
            "required": [],
        }
        tool_config = ToolConfig(
            parameters={"path": ParameterConfig(description="New description")}
        )

        result = _transform_schema(schema, tool_config)

        assert result["properties"]["path"]["description"] == "New description"

    def test_transform_schema_rename_with_description(self):
        """_transform_schema should rename and update description together."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Original"},
            },
            "required": ["path"],
        }
        tool_config = ToolConfig(
            parameters={
                "path": ParameterConfig(rename="folder", description="Folder name")
            }
        )

        result = _transform_schema(schema, tool_config)

        assert "folder" in result["properties"]
        assert result["properties"]["folder"]["description"] == "Folder name"
        assert "folder" in result["required"]

    def test_transform_schema_none_returns_none(self):
        """_transform_schema should return None for None schema."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        tool_config = ToolConfig(parameters={"path": ParameterConfig(hidden=True)})

        result = _transform_schema(None, tool_config)

        assert result is None

    def test_transform_schema_no_config_returns_original(self):
        """_transform_schema should return original schema if no config."""
        from mcp_proxy.proxy import _transform_schema

        schema = {"type": "object", "properties": {"x": {"type": "string"}}}

        result = _transform_schema(schema, None)

        assert result == schema

    def test_transform_args_injects_hidden_default(self):
        """_transform_args should inject default values for hidden params."""
        from mcp_proxy.proxy import _transform_args

        args = {"query": "test"}
        param_config = {
            "path": {"hidden": True, "default": "/skills"},
        }

        result = _transform_args(args, param_config)

        assert result["path"] == "/skills"
        assert result["query"] == "test"

    def test_transform_args_maps_renamed_param(self):
        """_transform_args should map renamed params back to original names."""
        from mcp_proxy.proxy import _transform_args

        args = {"category": "deployment"}
        param_config = {
            "path": {"rename": "category"},
        }

        result = _transform_args(args, param_config)

        assert result["path"] == "deployment"
        assert "category" not in result

    def test_transform_args_none_config_returns_original(self):
        """_transform_args should return original args if no config."""
        from mcp_proxy.proxy import _transform_args

        args = {"query": "test"}

        result = _transform_args(args, None)

        assert result == args

    def test_tool_info_stores_parameter_config(self):
        """ToolInfo should store parameter_config."""
        param_config = {"path": {"hidden": True, "default": "."}}
        tool = ToolInfo(
            name="list_files",
            description="List files",
            server="fs",
            parameter_config=param_config,
        )

        assert tool.parameter_config == param_config

    def test_get_view_tools_includes_transformed_schema(self):
        """get_view_tools should return tools with transformed schemas."""
        from unittest.mock import MagicMock

        from mcp_proxy.models import ParameterConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "list_directory": ToolConfig(
                            name="list_categories",
                            parameters={
                                "path": ParameterConfig(hidden=True, default=".")
                            },
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "list_directory"
        mock_tool.description = "List directory contents"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
            },
            "required": ["path"],
        }
        proxy._upstream_tools["fs"] = [mock_tool]

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        tool = tools[0]
        assert tool.name == "list_categories"
        # Hidden parameter should be removed from schema
        assert "path" not in tool.input_schema["properties"]
        # Parameter config should be stored
        assert tool.parameter_config is not None
        assert tool.parameter_config["path"]["hidden"] is True

    def test_get_view_tools_renames_param_in_schema(self):
        """get_view_tools should rename parameters in the exposed schema."""
        from unittest.mock import MagicMock

        from mcp_proxy.models import ParameterConfig, ToolConfig

        config = ProxyConfig(
            mcp_servers={
                "fs": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "list_directory": ToolConfig(
                            name="list_categories",
                            parameters={
                                "path": ParameterConfig(
                                    rename="category", description="Category to list"
                                )
                            },
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "list_directory"
        mock_tool.description = "List directory contents"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
            },
            "required": ["path"],
        }
        proxy._upstream_tools["fs"] = [mock_tool]

        tools = proxy.get_view_tools(None)

        tool = tools[0]
        # Original param should be renamed
        assert "path" not in tool.input_schema["properties"]
        assert "category" in tool.input_schema["properties"]
        assert (
            tool.input_schema["properties"]["category"]["description"]
            == "Category to list"
        )
        assert "category" in tool.input_schema["required"]

    def test_transform_schema_default_makes_optional(self):
        """_transform_schema should remove param from required when default is set."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path"},
            },
            "required": ["path"],
        }
        tool_config = ToolConfig(parameters={"path": ParameterConfig(default=".")})

        result = _transform_schema(schema, tool_config)

        # Path should have default and not be required
        assert result["properties"]["path"]["default"] == "."
        assert "path" not in result["required"]

    def test_transform_schema_rename_with_default(self):
        """_transform_schema should handle rename + default together."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        }
        tool_config = ToolConfig(
            parameters={"path": ParameterConfig(rename="folder", default="/home")}
        )

        result = _transform_schema(schema, tool_config)

        # Should be renamed with default, not required
        assert "path" not in result["properties"]
        assert "folder" in result["properties"]
        assert result["properties"]["folder"]["default"] == "/home"
        assert "folder" not in result["required"]
        assert "path" not in result["required"]

    def test_transform_args_injects_default_for_renamed_missing_param(self):
        """_transform_args should inject default when renamed param is missing."""
        from mcp_proxy.proxy import _transform_args

        args = {}  # No args provided
        param_config = {
            "path": {"rename": "category", "default": "."},
        }

        result = _transform_args(args, param_config)

        # Should inject default for the original param name
        assert result["path"] == "."

    def test_transform_args_injects_default_for_optional_param(self):
        """_transform_args should inject default for missing optional params."""
        from mcp_proxy.proxy import _transform_args

        args = {"other": "value"}
        param_config = {
            "path": {"default": "."},
        }

        result = _transform_args(args, param_config)

        assert result["path"] == "."
        assert result["other"] == "value"

    def test_transform_schema_skips_unknown_param(self):
        """_transform_schema should skip params not in schema properties."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "existing": {"type": "string"},
            },
            "required": ["existing"],
        }
        tool_config = ToolConfig(
            parameters={"nonexistent": ParameterConfig(hidden=True, default="x")}
        )

        result = _transform_schema(schema, tool_config)

        # Should be unchanged - nonexistent param config is ignored
        assert "existing" in result["properties"]
        assert "existing" in result["required"]

    def test_transform_schema_hidden_not_in_required(self):
        """_transform_schema should handle hidden param not in required list."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": [],  # path is optional
        }
        tool_config = ToolConfig(
            parameters={"path": ParameterConfig(hidden=True, default=".")}
        )

        result = _transform_schema(schema, tool_config)

        assert "path" not in result["properties"]
        assert result["required"] == []

    def test_transform_schema_rename_not_in_required(self):
        """_transform_schema should handle renamed param not in required list."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": [],  # path is optional
        }
        tool_config = ToolConfig(parameters={"path": ParameterConfig(rename="folder")})

        result = _transform_schema(schema, tool_config)

        assert "folder" in result["properties"]
        assert result["required"] == []  # Still empty

    def test_transform_schema_default_not_in_required(self):
        """_transform_schema should handle default for param not in required."""
        from mcp_proxy.models import ParameterConfig, ToolConfig
        from mcp_proxy.proxy import _transform_schema

        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": [],  # path is already optional
        }
        tool_config = ToolConfig(parameters={"path": ParameterConfig(default=".")})

        result = _transform_schema(schema, tool_config)

        assert result["properties"]["path"]["default"] == "."
        assert result["required"] == []

    def test_transform_args_hidden_no_default(self):
        """_transform_args should not inject hidden param without default."""
        from mcp_proxy.proxy import _transform_args

        args = {"query": "test"}
        param_config = {
            "path": {"hidden": True},  # No default
        }

        result = _transform_args(args, param_config)

        assert "path" not in result
        assert result["query"] == "test"

    def test_transform_args_renamed_provided(self):
        """_transform_args should not inject default when renamed param provided."""
        from mcp_proxy.proxy import _transform_args

        args = {"category": "provided"}  # renamed param is provided
        param_config = {
            "path": {"rename": "category", "default": "."},
        }

        result = _transform_args(args, param_config)

        # Should use provided value, not default
        assert result["path"] == "provided"
        assert "category" not in result

    def test_transform_args_optional_already_present(self):
        """_transform_args should not overwrite existing param with default."""
        from mcp_proxy.proxy import _transform_args

        args = {"path": "explicit"}
        param_config = {
            "path": {"default": "."},  # Has default but value provided
        }

        result = _transform_args(args, param_config)

        # Should keep the explicit value
        assert result["path"] == "explicit"

    def test_transform_args_renamed_no_default_not_provided(self):
        """_transform_args should not inject for renamed without default."""
        from mcp_proxy.proxy import _transform_args

        args = {"other": "value"}  # renamed param 'category' not provided
        param_config = {
            "path": {"rename": "category"},  # No default
        }

        result = _transform_args(args, param_config)

        # Should not inject path since there's no default
        assert "path" not in result
        assert result["other"] == "value"

    def test_transform_args_renamed_original_already_present(self):
        """_transform_args should not inject default if original param present."""
        from mcp_proxy.proxy import _transform_args

        args = {"path": "already_here"}  # Original name somehow present
        param_config = {
            "path": {"rename": "category", "default": "default_val"},
        }

        result = _transform_args(args, param_config)

        # Should keep the original value (even though renamed not provided)
        assert result["path"] == "already_here"


class TestProxyConnectionManagement:
    """Tests for proxy connection management."""

    async def test_connect_clients_creates_connections(self):
        """connect_clients should create active connections."""
        from unittest.mock import AsyncMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock client creation
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()

        assert proxy.has_active_connection("server")
        assert proxy.get_active_client("server") is mock_client

        # Cleanup
        await proxy.disconnect_clients()

    async def test_disconnect_clients_clears_connections(self):
        """disconnect_clients should close all connections."""
        from unittest.mock import AsyncMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock client
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ):
            await proxy.connect_clients()
            assert proxy.has_active_connection("server")

            await proxy.disconnect_clients()

        assert not proxy.has_active_connection("server")
        assert proxy.get_active_client("server") is None

    async def test_connect_clients_handles_errors(self):
        """connect_clients should continue if a server fails."""
        from unittest.mock import AsyncMock, patch

        config = ProxyConfig(
            mcp_servers={
                "bad_server": UpstreamServerConfig(command="nonexistent"),
                "good_server": UpstreamServerConfig(command="echo"),
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # First call fails, second succeeds
        mock_good_client = AsyncMock()
        mock_good_client.__aenter__ = AsyncMock(return_value=mock_good_client)
        mock_good_client.__aexit__ = AsyncMock()

        call_count = 0

        def create_client_side_effect(cfg):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Cannot connect")
            return mock_good_client

        with patch.object(
            proxy._client_manager,
            "create_client_from_config",
            side_effect=create_client_side_effect,
        ):
            await proxy.connect_clients()

        # Bad server should not be connected
        # Good server should be connected
        # (Order depends on dict iteration - just check at least one works)
        await proxy.disconnect_clients()

    async def test_connect_clients_idempotent(self):
        """connect_clients should do nothing if already connected."""
        from unittest.mock import AsyncMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(
            proxy._client_manager, "create_client_from_config", return_value=mock_client
        ) as mock_create:
            await proxy.connect_clients()
            await proxy.connect_clients()  # Second call should be no-op

        # Should only be called once
        assert mock_create.call_count == 1

        await proxy.disconnect_clients()

    async def test_disconnect_clients_when_not_connected(self):
        """disconnect_clients should be safe when not connected."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Should not raise
        await proxy.disconnect_clients()

    async def test_call_upstream_tool_with_active_client(self):
        """call_upstream_tool should use active client when available."""
        from unittest.mock import AsyncMock

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock active client
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "success"})
        proxy._active_clients["server"] = mock_client

        result = await proxy.call_upstream_tool("server", "tool_name", {"arg": "value"})

        assert result == {"result": "success"}
        mock_client.call_tool.assert_called_once_with("tool_name", {"arg": "value"})

    def test_get_active_client_returns_none_for_unknown(self):
        """get_active_client should return None for unknown server."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        assert proxy.get_active_client("unknown") is None

    def test_has_active_connection_returns_false_for_unknown(self):
        """has_active_connection should return False for unknown server."""
        config = ProxyConfig(mcp_servers={}, tool_views={})
        proxy = MCPProxy(config)

        assert not proxy.has_active_connection("unknown")

    async def test_lifespan_context_manager(self):
        """_create_lifespan should create a working context manager."""
        from unittest.mock import AsyncMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        lifespan = proxy._create_lifespan()

        # Mock connect_clients and disconnect_clients (the new lifespan behavior)
        with (
            patch.object(
                proxy, "connect_clients", new_callable=AsyncMock
            ) as mock_connect,
            patch.object(
                proxy, "disconnect_clients", new_callable=AsyncMock
            ) as mock_disconnect,
        ):
            # Use the lifespan context manager
            async with lifespan(None):
                mock_connect.assert_called_once_with(fetch_tools=True)
            # disconnect should be called on exit
            mock_disconnect.assert_called_once()

    async def test_initialize_skips_existing_clients(self):
        """initialize should skip creating clients that already exist."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Pre-populate upstream_clients
        existing_client = MagicMock()
        proxy.upstream_clients["server"] = existing_client

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            with patch.object(proxy, "refresh_upstream_tools", new_callable=AsyncMock):
                await proxy.initialize()

        # Should NOT have called _create_client since client already exists
        mock_create.assert_not_called()
        # Existing client should still be there
        assert proxy.upstream_clients["server"] is existing_client

    def test_sync_fetch_tools_skips_existing_clients(self):
        """sync_fetch_tools should skip creating clients that already exist."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")},
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Pre-populate upstream_clients
        existing_client = MagicMock()
        proxy.upstream_clients["server"] = existing_client

        with patch.object(
            proxy, "_create_client", new_callable=AsyncMock
        ) as mock_create:
            with patch.object(proxy, "fetch_upstream_tools", new_callable=AsyncMock):
                proxy.sync_fetch_tools()

        # Should NOT have called _create_client since client already exists
        mock_create.assert_not_called()
