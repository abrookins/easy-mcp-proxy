"""Tests for aliases in include_all views with view overrides."""

import pytest
from unittest.mock import MagicMock

from mcp_proxy.models import (
    ProxyConfig,
    UpstreamServerConfig,
    ToolConfig,
    ToolViewConfig,
    AliasConfig,
)
from mcp_proxy.proxy import MCPProxy


class TestAliasesInIncludeAllMode:
    """Tests for aliases in include_all views with view overrides."""

    def test_aliases_in_include_all_with_view_override(self):
        """include_all view with aliases in view override should create multiple tools."""
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

