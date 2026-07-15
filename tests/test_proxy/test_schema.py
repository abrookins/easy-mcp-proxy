"""Tests for input schema preservation and tool execution with schemas."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_proxy.models import (
    ParameterConfig,
    ProxyConfig,
    ToolConfig,
    UpstreamServerConfig,
)
from mcp_proxy.proxy import MCPProxy
from mcp_proxy.proxy.schema import (
    normalize_dict_arguments,
    resolve_schema_refs,
    transform_schema,
)
from tests.helpers import get_required_tool


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


def test_transform_schema_updates_combinator_required_names():
    """Renames and hides must apply inside oneOf/anyOf validation branches."""
    schema = {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "skill_name": {"type": "string"},
            "to_source": {"type": "string"},
        },
        "allOf": [
            {
                "anyOf": [
                    {"required": ["draft_id"]},
                    {"required": ["skill_name"]},
                ]
            },
            {"oneOf": [{"required": ["to_source"]}]},
        ],
    }
    config = ToolConfig(
        parameters={
            "to_source": ParameterConfig(rename="destination"),
            "skill_name": ParameterConfig(hidden=True),
        }
    )

    transformed = transform_schema(schema, config)

    assert set(transformed["properties"]) == {"draft_id", "destination"}
    assert transformed["allOf"][0]["anyOf"][1]["required"] == []
    assert transformed["allOf"][1]["oneOf"][0]["required"] == ["destination"]


def test_transform_schema_does_not_rename_nested_object_fields():
    """Top-level parameter transforms must not rewrite nested object fields."""
    schema = {
        "type": "object",
        "properties": {
            "destination": {"type": "string"},
            "options": {
                "type": "object",
                "properties": {"destination": {"type": "string"}},
                "required": ["destination"],
            },
        },
        "required": ["destination"],
    }
    config = ToolConfig(parameters={"destination": ParameterConfig(rename="to_source")})

    transformed = transform_schema(schema, config)

    assert set(transformed["properties"]) == {"options", "to_source"}
    assert transformed["required"] == ["to_source"]
    nested = transformed["properties"]["options"]
    assert set(nested["properties"]) == {"destination"}
    assert nested["required"] == ["destination"]


def test_transform_schema_preserves_boolean_composition_branches():
    """Boolean JSON Schema branches remain valid while object branches transform."""
    schema = {
        "anyOf": [
            True,
            {
                "type": "object",
                "properties": {"destination": {"type": "string"}},
                "required": ["destination"],
            },
        ]
    }
    config = ToolConfig(parameters={"destination": ParameterConfig(rename="to_source")})

    transformed = transform_schema(schema, config)

    assert transformed["anyOf"][0] is True
    assert set(transformed["anyOf"][1]["properties"]) == {"to_source"}
    assert transformed["anyOf"][1]["required"] == ["to_source"]


def test_normalize_args_returns_unchanged_for_non_object_properties():
    from mcp_proxy.proxy.schema import normalize_args_for_schema

    arguments = {"camelCase": "value"}
    assert normalize_args_for_schema(arguments, {"properties": []}) is arguments


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
        registered_tool = await get_required_tool(view_mcp, "my_tool")

        # Call with arguments
        await registered_tool.fn(arguments={"query": "test", "limit": 5})

        # Verify upstream was called with correct arguments
        mock_client.call_tool.assert_called_once_with(
            "my_tool", {"query": "test", "limit": 5}
        )


class TestSchemaRefResolution:
    """Tests for resolving $ref references in JSON schemas."""

    def test_resolve_refs_simple_ref(self):
        """resolve_schema_refs should inline simple $ref references."""
        schema = {
            "$defs": {
                "ActionType": {
                    "enum": ["create", "update", "delete"],
                    "type": "string",
                }
            },
            "properties": {
                "action": {
                    "$ref": "#/$defs/ActionType",
                    "description": "The action to perform.",
                }
            },
            "required": ["action"],
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        # Should inline the enum
        assert resolved["properties"]["action"]["enum"] == [
            "create",
            "update",
            "delete",
        ]
        assert resolved["properties"]["action"]["type"] == "string"
        # Should preserve the description from the original
        assert (
            resolved["properties"]["action"]["description"] == "The action to perform."
        )
        # Should remove $defs
        assert "$defs" not in resolved
        # Should not have $ref anymore
        assert "$ref" not in resolved["properties"]["action"]

    def test_resolve_refs_nested_ref(self):
        """resolve_schema_refs should handle nested $ref references."""
        schema = {
            "$defs": {
                "Transaction": {
                    "properties": {
                        "amount": {"type": "number"},
                        "account_id": {"type": "string"},
                    },
                    "type": "object",
                }
            },
            "properties": {
                "transactions": {
                    "items": {"$ref": "#/$defs/Transaction"},
                    "type": "array",
                }
            },
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        # Should inline the Transaction definition
        items = resolved["properties"]["transactions"]["items"]
        assert items["type"] == "object"
        assert items["properties"]["amount"]["type"] == "number"
        assert items["properties"]["account_id"]["type"] == "string"

    def test_resolve_refs_anyof_with_refs(self):
        """resolve_schema_refs should handle $ref inside anyOf."""
        schema = {
            "$defs": {
                "Model": {"properties": {"id": {"type": "string"}}, "type": "object"}
            },
            "properties": {
                "data": {
                    "anyOf": [
                        {"items": {"$ref": "#/$defs/Model"}, "type": "array"},
                        {"type": "null"},
                    ],
                    "default": None,
                }
            },
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        # Should resolve the ref inside anyOf
        array_option = resolved["properties"]["data"]["anyOf"][0]
        assert array_option["items"]["type"] == "object"
        assert array_option["items"]["properties"]["id"]["type"] == "string"

    def test_resolve_refs_no_refs(self):
        """resolve_schema_refs should handle schemas without refs."""
        schema = {
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        # Should be unchanged
        assert resolved == schema

    def test_resolve_refs_empty_schema(self):
        """resolve_schema_refs should handle empty schemas."""
        assert resolve_schema_refs({}) == {}
        assert resolve_schema_refs(None) is None

    def test_resolve_refs_definitions_key(self):
        """resolve_schema_refs should handle 'definitions' as well as '$defs'."""
        schema = {
            "definitions": {"MyType": {"type": "string"}},
            "properties": {"value": {"$ref": "#/definitions/MyType"}},
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        assert resolved["properties"]["value"]["type"] == "string"
        assert "definitions" not in resolved

    def test_resolve_refs_unresolvable_ref(self):
        """resolve_schema_refs should leave unresolvable $refs as-is."""
        schema = {
            "$defs": {"MyType": {"type": "string"}},
            "properties": {
                "value": {
                    "$ref": "https://example.com/external-schema.json"
                },  # External ref
                "other": {"$ref": "#/$defs/NonExistent"},  # Non-existent local ref
            },
            "type": "object",
        }

        resolved = resolve_schema_refs(schema)

        # External refs should be left as-is
        assert (
            resolved["properties"]["value"]["$ref"]
            == "https://example.com/external-schema.json"
        )
        # Non-existent local refs should also be left as-is
        assert resolved["properties"]["other"]["$ref"] == "#/$defs/NonExistent"


class TestNormalizeDictArguments:
    """Tests for dict-style argument normalization."""

    def test_accepts_json_object_string(self):
        """JSON object strings should be parsed into dictionaries."""
        assert normalize_dict_arguments('{"query": "test"}') == {"query": "test"}

    def test_rejects_invalid_json_string(self):
        """Invalid JSON strings should raise ValueError."""
        with pytest.raises(
            ValueError, match="arguments must be a dictionary or JSON object string"
        ):
            normalize_dict_arguments('{"query": ')

    def test_rejects_json_that_is_not_an_object(self):
        """JSON strings must decode to objects, not arrays or scalars."""
        with pytest.raises(ValueError, match="arguments JSON must decode to an object"):
            normalize_dict_arguments('["not", "an", "object"]')
