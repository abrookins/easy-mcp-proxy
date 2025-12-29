"""Tests for ToolInfo dataclass."""

import pytest

from mcp_proxy.proxy import ToolInfo


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

