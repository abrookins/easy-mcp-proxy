"""Search and description API tests for canonical tool metadata."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tests import run_server_async

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy, ToolInfo, ToolRegistry
from mcp_proxy.proxy.search_tools import UnknownToolError, create_describe_tool_wrapper
from mcp_proxy.search import SearchTool
from tests.helpers import get_required_tool


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolInfo(
                name="promote_skill_draft",
                description="Promote a draft",
                server="skills",
                input_schema={
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                        "to_source": {"type": "string"},
                    },
                    "required": ["draft_id", "to_source"],
                },
            ),
            ToolInfo(
                name="find_skills",
                description="Find installed skills",
                server="skills",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            ),
        ]
    )


async def test_broad_search_is_compact_but_includes_derived_metadata():
    """Default search results should teach names without returning full schemas."""
    search = SearchTool("skills_search_tools", "skills", _registry())

    result = await search()

    assert result["total"] == 2
    assert "inputSchema" not in result["tools"][0]
    assert result["tools"][0]["accepted_parameter_names"] == [
        "draft_id",
        "dry_run",
        "to_source",
    ]
    assert result["tools"][0]["supports_dry_run"] is True


async def test_search_include_schema_returns_complete_exposed_schema():
    """Callers may opt in to complete canonical schemas per search result."""
    registry = _registry()
    search = SearchTool("skills_search_tools", "skills", registry)

    result = await search(query="promote", include_schema=True)

    assert (
        result["tools"][0]["inputSchema"]
        == registry.get("promote_skill_draft").input_schema
    )


async def test_search_ranking_and_pagination_ignore_schema_text():
    """Schema content should not influence ranking or pagination behavior."""
    registry = ToolRegistry(
        [
            ToolInfo(
                name="unrelated",
                description="No match",
                input_schema={
                    "properties": {"needle": {"description": "memory memory"}}
                },
            ),
            ToolInfo(name="memory", description="Exact match"),
            ToolInfo(name="search_memory", description="Search memory"),
        ]
    )
    search = SearchTool("search", "view", registry, threshold=50)

    first = await search(query="memory", limit=1, offset=0, include_schema=True)
    second = await search(query="memory", limit=1, offset=1, include_schema=True)

    assert first["total"] == 2
    assert first["tools"][0]["name"] == "memory"
    assert second["tools"][0]["name"] == "search_memory"


async def test_description_lookup_works_for_view_and_per_server_exposure():
    """Both search exposure modes should register exact description tools."""
    view_proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={"skills": {"command": "echo"}},
            tool_views={
                "catalog": {
                    "exposure_mode": "search",
                    "tools": {
                        "skills": {
                            "find_skills": {"description": "Find installed skills"}
                        }
                    },
                }
            },
        )
    )
    server_proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={"skills": {"command": "echo"}},
            tool_views={
                "catalog": {
                    "exposure_mode": "search_per_server",
                    "tools": {
                        "skills": {
                            "find_skills": {"description": "Find installed skills"}
                        }
                    },
                }
            },
        )
    )

    view_tool = await get_required_tool(
        view_proxy.get_view_mcp("catalog"), "catalog_describe_tool"
    )
    server_tool = await get_required_tool(
        server_proxy.get_view_mcp("catalog"), "skills_describe_tool"
    )

    assert (await view_tool.fn("find_skills"))["name"] == "find_skills"
    assert (await server_tool.fn("find_skills"))["name"] == "find_skills"


async def test_unknown_description_has_optional_strong_suggestion():
    """Unknown names should always list choices and suggest only strong matches."""
    wrapper = create_describe_tool_wrapper(
        _registry(), "skills_describe_tool", "skills"
    )

    with pytest.raises(UnknownToolError) as strong:
        await wrapper("promote_skill_darft")
    assert strong.value.payload["did_you_mean"] == "promote_skill_draft"
    assert strong.value.payload["available_tool_names"] == [
        "find_skills",
        "promote_skill_draft",
    ]

    with pytest.raises(UnknownToolError) as weak:
        await wrapper("totally_different")
    assert "did_you_mean" not in weak.value.payload


async def test_description_lookup_never_calls_upstream_and_refreshes_in_place():
    """Description reads should remain local while refresh replaces their snapshot."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "include_all": True,
            }
        },
    )
    proxy = MCPProxy(config)
    client = AsyncMock()
    proxy.upstream_clients = {"skills": client}
    first = MagicMock(
        name="first",
        description="First version",
        inputSchema={"type": "object", "properties": {}},
    )
    first.name = "inspect"
    proxy._upstream_tools["skills"] = [first]
    describe = await get_required_tool(
        proxy.get_view_mcp("catalog"), "catalog_describe_tool"
    )

    assert (await describe.fn("inspect"))["description"] == "First version"
    client.list_tools.assert_not_awaited()

    second = MagicMock(
        description="Second version",
        inputSchema={"type": "object", "properties": {}},
    )
    second.name = "inspect"
    proxy._upstream_tools["skills"] = [second]
    proxy._refresh_tool_registries()

    assert (await describe.fn("inspect"))["description"] == "Second version"
    client.list_tools.assert_not_awaited()


async def test_mcp_protocol_lists_and_calls_all_three_meta_tools():
    """An MCP client should discover and call search, describe, and call tools."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "tools": {"skills": {"find_skills": {"description": "Find"}}},
            }
        },
    )
    proxy = MCPProxy(config)
    upstream = AsyncMock()
    upstream.call_tool.return_value = {"skills": []}
    proxy.views["catalog"]._upstream_clients = {"skills": upstream}
    mcp = proxy.get_view_mcp("catalog")

    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {
            "catalog_search_tools",
            "catalog_describe_tool",
            "catalog_call_tool",
        } <= names
        searched = await client.call_tool("catalog_search_tools", {})
        described = await client.call_tool(
            "catalog_describe_tool", {"tool_name": "find_skills"}
        )
        called = await client.call_tool(
            "catalog_call_tool", {"tool_name": "find_skills", "arguments": {}}
        )

    assert json.loads(searched.content[0].text)["tools"][0]["name"] == "find_skills"
    assert json.loads(described.content[0].text)["name"] == "find_skills"
    assert json.loads(called.content[0].text) == {"skills": []}


async def test_http_transport_uses_the_same_search_and_description_contracts():
    """HTTP and in-memory MCP transports should serialize identical metadata."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "tools": {"skills": {"find_skills": {"description": "Find"}}},
            }
        },
    )
    proxy = MCPProxy(config)
    mcp = proxy.get_view_mcp("catalog")

    async with Client(mcp) as local:
        local_search = await local.call_tool(
            "catalog_search_tools", {"include_schema": True}
        )
        local_description = await local.call_tool(
            "catalog_describe_tool", {"tool_name": "find_skills"}
        )

    async with run_server_async(mcp) as url:
        async with Client(transport=StreamableHttpTransport(url)) as http:
            http_search = await http.call_tool(
                "catalog_search_tools", {"include_schema": True}
            )
            http_description = await http.call_tool(
                "catalog_describe_tool", {"tool_name": "find_skills"}
            )

    assert json.loads(http_search.content[0].text) == json.loads(
        local_search.content[0].text
    )
    assert json.loads(http_description.content[0].text) == json.loads(
        local_description.content[0].text
    )


async def test_unknown_description_is_an_mcp_tool_error_with_json_payload():
    """MCP transports should preserve the structured unknown-tool error text."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "tools": {"skills": {"find_skills": {}}},
            }
        },
    )
    mcp = MCPProxy(config).get_view_mcp("catalog")

    async with Client(mcp) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool("catalog_describe_tool", {"tool_name": "find_skill"})

    error_text = str(exc_info.value)
    payload = json.loads(error_text[error_text.index("{") :])
    assert payload["error"] == "unknown_tool"
    assert payload["did_you_mean"] == "find_skills"


@pytest.mark.parametrize(
    ("mode", "mode_guidance"),
    [
        ("direct", "Call the listed tools directly by exposed name."),
        ("search", "`catalog_search_tools`"),
        ("search_per_server", "Each upstream server exposes its own"),
    ],
)
def test_registry_generated_instructions_cover_every_exposure_mode(mode, mode_guidance):
    """Instruction text should be a deterministic rendering of canonical data."""
    registry = ToolRegistry(
        [
            ToolInfo(
                name="preview",
                description="Preview a change.",
                input_schema={
                    "properties": {
                        "target": {"type": "string"},
                        "dry_run": {"type": "boolean"},
                    }
                },
            )
        ]
    )

    instructions = registry.instructions("catalog", mode)

    assert instructions.startswith("# Exposed tool registry: catalog\n")
    assert f"Exposure mode: `{mode}`." in instructions
    assert mode_guidance in instructions
    assert (
        "- `preview`: Preview a change. Accepted parameters: `dry_run`, "
        "`target`. Dry-run preview supported."
    ) in instructions


async def test_per_tool_instructions_match_description_schema():
    """Instruction and description lookups must consume the same registry object."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "include_all": True,
            }
        },
    )
    proxy = MCPProxy(config)
    upstream = MagicMock()
    upstream.name = "find_skills"
    upstream.description = "Find skills"
    upstream.inputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    proxy._upstream_tools["skills"] = [upstream]
    mcp = proxy.get_view_mcp("catalog")
    describe = await get_required_tool(mcp, "catalog_describe_tool")
    instructions = await get_required_tool(mcp, "get_tool_instructions")

    described = await describe.fn("find_skills")
    instructed = instructions.fn("find_skills")

    assert instructed["inputSchema"] == described["inputSchema"]
    assert (
        instructed["accepted_parameter_names"] == described["accepted_parameter_names"]
    )
    assert "usage_guidance" in instructed


async def test_instruction_lookup_missing_tool_has_structured_suggestion():
    """Per-tool help should fail explicitly instead of returning unrelated prose."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "tools": {"skills": {"find_skills": {}}},
            }
        },
    )
    instructions = await get_required_tool(
        MCPProxy(config).get_view_mcp("catalog"), "get_tool_instructions"
    )

    with pytest.raises(UnknownToolError) as exc_info:
        instructions.fn("find_skill")

    assert exc_info.value.payload["did_you_mean"] == "find_skills"
    assert exc_info.value.payload["available_tool_names"] == ["find_skills"]


async def test_registry_refresh_changes_live_generated_instructions():
    """Existing instruction closures should read replaced metadata snapshots."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            "catalog": {
                "exposure_mode": "search",
                "include_all": True,
            }
        },
    )
    proxy = MCPProxy(config)
    first = MagicMock()
    first.name = "first_tool"
    first.description = "First"
    first.inputSchema = {"type": "object", "properties": {}}
    proxy._upstream_tools["skills"] = [first]
    mcp = proxy.get_view_mcp("catalog")
    instructions = await get_required_tool(mcp, "get_tool_instructions")
    assert "`first_tool`" in instructions.fn()

    second = MagicMock()
    second.name = "second_tool"
    second.description = "Second"
    second.inputSchema = {"type": "object", "properties": {}}
    proxy._upstream_tools["skills"] = [second]
    proxy._refresh_tool_registries()

    refreshed = instructions.fn()
    assert "`second_tool`" in refreshed
    assert "`first_tool`" not in refreshed
    assert "`second_tool`" in mcp.instructions


async def test_per_server_registry_refresh_replaces_server_snapshot():
    """Per-server describe closures should receive a complete refreshed batch."""
    proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={"skills": {"command": "echo"}},
            tool_views={
                "catalog": {
                    "exposure_mode": "search_per_server",
                    "include_all": True,
                }
            },
        )
    )
    first = MagicMock(
        name="first",
        description="First",
        inputSchema={"type": "object", "properties": {}},
    )
    first.name = "first"
    proxy._upstream_tools["skills"] = [first]
    mcp = proxy.get_view_mcp("catalog")
    describe = await get_required_tool(mcp, "skills_describe_tool")
    assert (await describe.fn("first"))["name"] == "first"

    second = MagicMock(
        name="second",
        description="Second",
        inputSchema={"type": "object", "properties": {}},
    )
    second.name = "second"
    proxy._upstream_tools["skills"] = [second]
    proxy._refresh_tool_registries()

    assert (await describe.fn("second"))["name"] == "second"


async def test_registry_and_upstream_guidance_are_visibly_separate():
    """Workflow prose must be labeled as secondary to live registry metadata."""
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={"catalog": {}},
    )
    proxy = MCPProxy(config)
    proxy.upstream_instructions["skills"] = "Follow this upstream workflow."
    instructions = await get_required_tool(
        proxy.get_view_mcp("catalog"), "get_tool_instructions"
    )

    rendered = instructions.fn()

    assert "live proxy registry" in rendered
    assert "Upstream workflow guidance (non-authoritative)" in rendered
    assert rendered.index("live proxy registry") < rendered.index(
        "Follow this upstream workflow."
    )
