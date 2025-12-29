"""Tests for parameter binding (hidden params, defaults, etc.)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp_proxy.models import (
    ProxyConfig,
    UpstreamServerConfig,
    ToolConfig,
    ToolViewConfig,
    ParameterConfig,
)
from mcp_proxy.proxy import MCPProxy


class TestParameterBinding:
    """Tests for parameter binding (hidden params, defaults, etc.)."""

    def test_get_view_tools_includes_parameter_config(self):
        """get_view_tools should include parameter_config from tool config."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "list_files": ToolConfig(
                            description="List files",
                            parameters={
                                "path": ParameterConfig(hidden=True, default="/data")
                            },
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        assert tools[0].parameter_config is not None
        assert "path" in tools[0].parameter_config
        assert tools[0].parameter_config["path"]["hidden"] is True
        assert tools[0].parameter_config["path"]["default"] == "/data"

    def test_parameter_config_with_multiple_params(self):
        """parameter_config should handle multiple parameters."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "search": ToolConfig(
                            description="Search",
                            parameters={
                                "path": ParameterConfig(hidden=True, default="."),
                                "limit": ParameterConfig(default=10),
                                "format": ParameterConfig(hidden=True, default="json"),
                            },
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools(None)

        assert len(tools) == 1
        param_config = tools[0].parameter_config

        assert param_config["path"]["hidden"] is True
        assert param_config["path"]["default"] == "."

        assert param_config["limit"]["hidden"] is False
        assert param_config["limit"]["default"] == 10

        assert param_config["format"]["hidden"] is True
        assert param_config["format"]["default"] == "json"

    def test_parameter_config_in_view_override(self):
        """View override should be able to set parameter_config."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={"my_tool": ToolConfig(description="Tool")},
                )
            },
            tool_views={
                "test-view": ToolViewConfig(
                    description="Test view",
                    tools={
                        "server": {
                            "my_tool": ToolConfig(
                                parameters={
                                    "hidden_param": ParameterConfig(
                                        hidden=True, default="secret"
                                    )
                                }
                            )
                        }
                    },
                )
            },
        )
        proxy = MCPProxy(config)

        tools = proxy.get_view_tools("test-view")

        assert len(tools) == 1
        assert tools[0].parameter_config is not None
        assert tools[0].parameter_config["hidden_param"]["hidden"] is True
        assert tools[0].parameter_config["hidden_param"]["default"] == "secret"

    async def test_hidden_param_removed_from_schema(self):
        """Hidden parameters should be removed from exposed input schema."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "list_files": ToolConfig(
                            description="List files",
                            parameters={
                                "path": ParameterConfig(hidden=True, default="/data")
                            },
                        )
                    },
                )
            },
            tool_views={},
        )
        proxy = MCPProxy(config)

        # Mock upstream tool with schema including the hidden param
        mock_tool = MagicMock()
        mock_tool.name = "list_files"
        mock_tool.description = "List files"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "pattern": {"type": "string", "description": "File pattern"},
            },
            "required": ["path"],
        }

        mock_client = AsyncMock()
        mock_client.list_tools.return_value = [mock_tool]
        proxy.upstream_clients = {"server": mock_client}

        await proxy.fetch_upstream_tools("server")

        tools = proxy.get_view_tools(None)

        # The tool should have the schema, but 'path' should be marked as hidden
        assert len(tools) == 1
        assert tools[0].parameter_config["path"]["hidden"] is True

    async def test_default_param_injected_on_call(self):
        """Default parameters should be injected when calling upstream."""
        config = ProxyConfig(
            mcp_servers={
                "server": UpstreamServerConfig(
                    command="echo",
                    tools={
                        "list_files": ToolConfig(
                            description="List files",
                            parameters={
                                "path": ParameterConfig(hidden=True, default="/data")
                            },
                        )
                    },
                )
            },
            tool_views={
                "view": {
                    "exposure_mode": "direct",
                    "tools": {"server": {"list_files": {}}},
                }
            },
        )
        proxy = MCPProxy(config)

        # Mock upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"files": ["a.txt", "b.txt"]}
        proxy.upstream_clients = {"server": mock_client}
        proxy.views["view"]._upstream_clients = {"server": mock_client}

        # Get the view MCP and find the tool
        view_mcp = proxy.get_view_mcp("view")
        registered_tool = None
        for tool in view_mcp._tool_manager._tools.values():
            if tool.name == "list_files":
                registered_tool = tool
                break

        assert registered_tool is not None

        # Call without providing 'path' - it should be injected
        await registered_tool.fn(arguments={"pattern": "*.txt"})

        # Verify upstream was called with the default path injected
        call_args = mock_client.call_tool.call_args
        assert call_args[0][0] == "list_files"
        assert call_args[0][1]["path"] == "/data"
        assert call_args[0][1]["pattern"] == "*.txt"

