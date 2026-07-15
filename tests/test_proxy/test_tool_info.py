"""Tests for ToolInfo dataclass."""

from mcp_proxy.proxy import ToolInfo, ToolRegistry


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

    def test_tool_info_serializes_canonical_metadata(self):
        """ToolInfo should serialize stable exposed metadata."""
        schema = {
            "type": "object",
            "properties": {
                "zeta": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "alpha": {"type": "integer"},
            },
        }
        tool = ToolInfo(
            name="preview",
            description="Preview a change",
            server="skills",
            input_schema=schema,
            original_name="apply_change",
        )

        metadata = tool.to_metadata()

        assert metadata == {
            "name": "preview",
            "description": "Preview a change",
            "server": "skills",
            "original_name": "apply_change",
            "accepted_parameter_names": ["alpha", "dry_run", "zeta"],
            "supports_dry_run": True,
            "inputSchema": schema,
        }
        metadata["inputSchema"]["properties"].clear()
        assert tool.input_schema == schema

    def test_tool_info_without_schema_has_empty_contract(self):
        """Tools without schemas should not claim validation metadata."""
        tool = ToolInfo(name="unknown_contract", server="server")

        assert tool.accepted_parameter_names == []
        assert tool.supports_dry_run is False
        assert tool.to_metadata() == {
            "name": "unknown_contract",
            "description": "",
            "server": "server",
            "original_name": "unknown_contract",
            "accepted_parameter_names": [],
            "supports_dry_run": False,
            "inputSchema": {},
        }
        assert "inputSchema" not in tool.to_metadata(include_schema=False)

    def test_dry_run_support_requires_boolean_property(self):
        """A non-boolean dry_run property should not advertise preview support."""
        tool = ToolInfo(
            name="bad_preview",
            input_schema={
                "type": "object",
                "properties": {"dry_run": {"type": "string"}},
            },
        )

        assert tool.supports_dry_run is False

    def test_schema_without_properties_has_empty_derived_metadata(self):
        """An object schema may validly omit a properties mapping."""
        tool = ToolInfo(name="no_properties", input_schema={"type": "object"})

        assert tool.accepted_parameter_names == []
        assert tool.supports_dry_run is False


class TestToolRegistry:
    """Tests for atomic canonical metadata snapshots."""

    def test_registry_replaces_complete_snapshot(self):
        """Registry replacement should update lookup and serialized output."""
        first = ToolInfo(name="first", server="one")
        second = ToolInfo(name="second", server="two")
        registry = ToolRegistry([first])

        assert registry.tools == (first,)
        assert registry.get("first") is first

        registry.replace([second])

        assert registry.tools == (second,)
        assert registry.get("first") is None
        assert registry.get("second") is second
        assert registry.metadata(include_schema=False) == [
            second.to_metadata(include_schema=False)
        ]
