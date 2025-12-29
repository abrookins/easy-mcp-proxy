"""Tests for multiple aliases from a single upstream tool."""

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


class TestToolAliases:
    """Tests for multiple aliases from a single upstream tool."""

    def test_aliases_creates_multiple_tools_in_default_view(self):
        """Aliases should create multiple tools from one upstream tool."""
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

