"""Tests for input schema preservation and tool execution with schemas."""

from unittest.mock import AsyncMock, MagicMock

from mcp_proxy.models import ProxyConfig, ToolConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy


class TestInputSchemaPreservation:
    """Tests for input schema preservation from upstream tools."""

    async def test_fetch_upstream_tools_preserves_input_schema(self):
        """fetch_upstream_tools should preserve inputSchema from upstream."""
        config = ProxyConfig(
            mcp_servers={"server": UpstreamServerConfig(command="echo")}, tool_views={}
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "search_code"
        mock_tool.description = "Search code"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        # Check schema is preserved in _upstream_tools
        assert "server" in proxy._upstream_tools
        assert len(proxy._upstream_tools["server"]) == 1
        stored_tool = proxy._upstream_tools["server"][0]
        assert stored_tool.inputSchema == mock_tool.inputSchema

    async def test_get_view_tools_includes_input_schema(self):
        """get_view_tools should include input_schema from upstream."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"search_code": ToolConfig(description="Search")},
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "search_code"
        mock_tool.description = "Search code"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].input_schema is not None
        assert tools[0].input_schema["properties"]["query"]["type"] == "string"

    async def test_input_schema_preserved_with_name_alias(self):
        """Input schema should be preserved when tool has name alias."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "original_name": ToolConfig(
                            name="aliased_name", description="Aliased tool"
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema
        mock_tool = MagicMock()
        mock_tool.name = "original_name"
        mock_tool.description = "Original description"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"param": {"type": "string"}},
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].name == "aliased_name"
        assert tools[0].input_schema is not None
        assert tools[0].input_schema["properties"]["param"]["type"] == "string"


class TestToolExecutionWithInputSchema:
    """Tests for tool execution with input schema validation."""

    async def test_tool_execution_passes_arguments_correctly(self):
        """Tool execution should pass arguments to upstream correctly."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo", tools={"my_tool": ToolConfig(description="Test")}
                )
            },
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"my_tool": {}}},
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"result": "success"}
        proxy.upstream_clients = {"server": mock_client}
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP and find the tool
        view_mcp = proxy.get_view_mcp("view")
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "my_tool":
                registered_tool = tool
                break

        assert registered_tool is not None

        # Call with arguments
        await registered_tool.fn(arguments={"query": "test", "limit": 5})

        # Verify upstream was called with correct arguments
        mock_client.call_tool.assert_called_once_with(
            "my_tool", {"query": "test", "limit": 5}
        )
