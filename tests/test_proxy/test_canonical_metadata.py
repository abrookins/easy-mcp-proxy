"""Tests for canonical metadata across proxy exposure modes."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from fastmcp import FastMCP

from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy, ToolInfo, ToolRegistry
from tests.helpers import get_required_tool


def _upstream_tool(
    name: str = "mutate",
    description: str = "Original description",
    schema: dict | None = None,
) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = schema
    return tool


def test_raw_and_exposed_metadata_are_distinct_after_all_transforms():
    """Canonical metadata should describe the transformed public contract."""
    raw_schema = {
        "$defs": {"Text": {"type": "string", "minLength": 1}},
        "type": "object",
        "properties": {
            "destination": {"$ref": "#/$defs/Text"},
            "secret": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["destination", "secret", "count"],
    }
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "public": {
                "tools": {
                    "skills": {
                        "mutate": {
                            "name": "promote",
                            "description": "Promote safely. {original}",
                            "parameters": {
                                "destination": {
                                    "rename": "to_source",
                                    "description": "Promotion target",
                                },
                                "secret": {"hidden": True, "default": "fixed"},
                                "count": {"default": 1},
                            },
                        }
                    }
                }
            }
        },
    )
    proxy = MCPProxy(config)
    raw_tool = _upstream_tool(schema=raw_schema)
    proxy._upstream_tools["skills"] = [raw_tool]

    exposed = proxy.get_view_tools("public")[0]

    assert raw_tool.inputSchema == raw_schema
    assert exposed.name == "promote"
    assert exposed.original_name == "mutate"
    assert exposed.description == "Promote safely. Original description"
    assert exposed.accepted_parameter_names == ["count", "to_source"]
    assert "$defs" not in exposed.input_schema
    assert exposed.input_schema["properties"]["to_source"] == {
        "type": "string",
        "minLength": 1,
        "description": "Promotion target",
    }
    assert exposed.input_schema["properties"]["count"]["default"] == 1
    assert exposed.input_schema["required"] == ["to_source"]


def test_hidden_parameters_never_serialize_in_canonical_metadata():
    """Hidden upstream parameters must not leak through derived fields or schema."""
    tool = ToolInfo(
        name="safe",
        input_schema={
            "type": "object",
            "properties": {"visible": {"type": "string"}},
        },
        parameter_config={"secret": {"hidden": True, "default": "fixed"}},
    )

    metadata = tool.to_metadata()

    assert "secret" not in metadata["accepted_parameter_names"]
    assert "secret" not in metadata["inputSchema"]["properties"]


def test_alias_metadata_retains_exposed_and_original_names():
    """Each alias should retain its public and upstream identities."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "public": {
                "tools": {
                    "skills": {
                        "mutate": {
                            "aliases": [
                                {"name": "promote", "description": "Promote"},
                                {"name": "publish", "description": "Publish"},
                            ]
                        }
                    }
                }
            }
        },
    )
    proxy = MCPProxy(config)
    proxy._upstream_tools["skills"] = [
        _upstream_tool(schema={"type": "object", "properties": {}})
    ]

    metadata = {
        item["name"]: item
        for item in ToolRegistry(proxy.get_view_tools("public")).metadata()
    }

    assert metadata["promote"]["original_name"] == "mutate"
    assert metadata["publish"]["original_name"] == "mutate"


def test_custom_and_composite_tools_publish_canonical_schemas():
    """Locally defined tools should use the same metadata representation."""

    @custom_tool(name="local", description="Local tool")
    async def local(query: str, limit: int = 5) -> dict:
        return {"query": query, "limit": limit}

    config = ProxyConfig(
        tool_views={
            "public": {
                "composite_tools": {
                    "fan_out": {
                        "description": "Fan out",
                        "inputs": {"query": {"type": "string", "required": True}},
                        "parallel": {},
                    }
                }
            }
        }
    )
    proxy = MCPProxy(config)
    proxy.views["public"].custom_tools["local"] = local

    by_name = {tool.name: tool for tool in proxy.get_view_tools("public")}

    assert by_name["local"].accepted_parameter_names == ["limit", "query"]
    assert by_name["local"].input_schema["required"] == ["query"]
    assert by_name["fan_out"].accepted_parameter_names == ["query"]
    assert by_name["fan_out"].input_schema["required"] == ["query"]


def test_tool_without_schema_has_an_explicit_empty_contract():
    """Missing upstream schemas should serialize safely and deterministically."""
    metadata = ToolInfo(name="legacy").to_metadata()

    assert metadata["inputSchema"] == {}
    assert metadata["accepted_parameter_names"] == []
    assert metadata["supports_dry_run"] is False


def test_accepted_names_are_sorted_and_dry_run_requires_boolean_schema():
    """Derived metadata must be stable and use the exposed property type."""
    valid = ToolInfo(
        name="valid",
        input_schema={
            "properties": {
                "z": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "a": {"type": "string"},
            }
        },
    )
    invalid = ToolInfo(
        name="invalid",
        input_schema={"properties": {"dry_run": {"type": "string"}}},
    )

    assert valid.accepted_parameter_names == ["a", "dry_run", "z"]
    assert valid.supports_dry_run is True
    assert invalid.supports_dry_run is False


def test_registry_readers_never_observe_a_partial_refresh():
    """Concurrent readers should see either complete old or complete new batches."""
    old = [ToolInfo(name=f"old_{index}") for index in range(20)]
    new = [ToolInfo(name=f"new_{index}") for index in range(30)]
    registry = ToolRegistry(old)

    def refresh() -> None:
        for _ in range(500):
            registry.replace(new)
            registry.replace(old)

    def read() -> None:
        for _ in range(1000):
            names = [item["name"] for item in registry.metadata(False)]
            assert len(names) in {20, 30}
            assert all(name.startswith("old_") for name in names) or all(
                name.startswith("new_") for name in names
            )

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(refresh)]
        futures.extend(executor.submit(read) for _ in range(4))
        for future in futures:
            future.result()


async def test_direct_fastmcp_registration_uses_canonical_exposed_schema():
    """Direct registration must preserve the schema advertised by metadata."""
    config = ProxyConfig(
        mcp_servers={
            "skills": {
                "command": "echo",
                "tools": {
                    "mutate": {
                        "parameters": {
                            "destination": {"rename": "to_source"},
                            "secret": {"hidden": True, "default": "fixed"},
                        }
                    }
                },
            }
        }
    )
    proxy = MCPProxy(config)
    proxy._upstream_tools["skills"] = [
        _upstream_tool(
            schema={
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "secret": {"type": "string"},
                },
                "required": ["destination", "secret"],
            }
        )
    ]
    canonical = proxy.get_view_tools(None)[0]
    mcp = FastMCP("test")

    proxy._register_tools_on_mcp(mcp, [canonical])
    registered = await get_required_tool(mcp, "mutate")

    assert registered.parameters == canonical.input_schema
