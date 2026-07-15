"""Cross-repository lifecycle tests with a real Upskill stdio server."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy
from mcp_proxy.proxy.validation import ToolArgumentValidationError
from tests.helpers import get_required_tool

UPSKILL_REPO = Path(
    os.environ.get("UPSKILL_REPO", Path(__file__).resolve().parents[2] / "upskill")
)


@pytest.fixture(scope="session")
def upskill_binary(tmp_path_factory) -> Path:
    """Build the sibling Upskill checkout once for real stdio integration tests."""
    if not (UPSKILL_REPO / "go.mod").exists():
        pytest.skip(f"Upskill checkout not found at {UPSKILL_REPO}; set UPSKILL_REPO")
    binary = tmp_path_factory.mktemp("upskill-bin") / "upskill"
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/upskill"],
        cwd=UPSKILL_REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


@pytest.fixture
def upskill_state(tmp_path, upskill_binary):
    """Create isolated Upskill configuration and a writable fixture source."""
    home = tmp_path / "home"
    source = tmp_path / "personal-source"
    home.mkdir()
    source.mkdir()
    config_path = home / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "src_fixture_personal",
                        "name": "personal",
                        "source": str(source),
                        "scope": "personal",
                        "write_policy": "direct_allowed",
                    }
                ]
            }
        )
    )
    return {
        "binary": upskill_binary,
        "home": home,
        "config": config_path,
        "source": source,
    }


def _upstream_config(state) -> dict:
    return {
        "command": str(state["binary"]),
        "args": ["mcp"],
        "cwd": str(UPSKILL_REPO),
        "env": {
            "UPSKILL_HOME": str(state["home"]),
            "UPSKILL_CONFIG": str(state["config"]),
        },
    }


async def _proxy_for_state(state, *, view_tool=None) -> MCPProxy:
    view = {"exposure_mode": "search_per_server", "include_all": True}
    if view_tool is not None:
        view = {
            "exposure_mode": "search_per_server",
            "tools": {"skills": {"promote_skill_draft": view_tool}},
        }
    proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={"skills": _upstream_config(state)},
            tool_views={"skills": view},
        )
    )
    await proxy.initialize()
    return proxy


def _result_payload(result):
    if isinstance(result, dict):
        return result
    text = "".join(
        item.text for item in result.content if getattr(item, "text", None) is not None
    )
    return json.loads(text)


async def _meta_tools(proxy):
    mcp = proxy.get_view_mcp("skills")
    return (
        await get_required_tool(mcp, "skills_search_tools"),
        await get_required_tool(mcp, "skills_describe_tool"),
        await get_required_tool(mcp, "skills_call_tool"),
    )


async def _call(call_tool, tool_name, arguments):
    return _result_payload(await call_tool.fn(tool_name=tool_name, arguments=arguments))


async def test_search_describe_validate_preview_apply_and_read_back(upskill_state):
    """A real proxied agent lifecycle should be discoverable and state-safe."""
    proxy = await _proxy_for_state(upskill_state)
    search, describe, call = await _meta_tools(proxy)

    found = await search.fn(query="promote skill draft", include_schema=True)
    assert found["tools"][0]["name"] == "promote_skill_draft"
    assert "to_source" in found["tools"][0]["inputSchema"]["properties"]

    described = await describe.fn(tool_name="promote_skill_draft")
    assert described["inputSchema"] == found["tools"][0]["inputSchema"]
    assert "to_source" in described["accepted_parameter_names"]

    original_call = proxy.views["skills"].call_tool
    proxy.views["skills"].call_tool = AsyncMock(wraps=original_call)
    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await call.fn(
            tool_name="promote_skill_draft",
            arguments={"draft_id": "draft:proxy-e2e", "destination": "personal"},
        )
    assert exc_info.value.payload["did_you_mean"] == {"destination": "to_source"}
    proxy.views["skills"].call_tool.assert_not_awaited()

    created = await _call(call, "create_skill_draft", {"skill_name": "proxy-e2e"})
    assert created["skill_id"] == "draft:proxy-e2e"
    destination = upskill_state["source"] / "proxy-e2e" / "SKILL.md"

    preview = await _call(
        call,
        "promote_skill_draft",
        {
            "draft_id": "draft:proxy-e2e",
            "to_source": "src_fixture_personal",
            "dry_run": True,
        },
    )
    assert preview["dry_run"] is True
    assert preview["applied"] is False
    assert preview["canonical_resources"]["source_id"] == "src_fixture_personal"
    assert not destination.exists()

    applied = await _call(
        call,
        "promote_skill_draft",
        {
            "draft_id": "draft:proxy-e2e",
            "to_source": str(upskill_state["source"]),
            "dry_run": False,
        },
    )
    assert applied["applied"] is True
    assert destination.exists()

    read_back = await _call(
        call,
        "find_source_skills",
        {"source": "personal", "query": "proxy-e2e"},
    )
    assert any(item["name"] == "proxy-e2e" for item in read_back["skills"])


async def test_renamed_and_hidden_lifecycle_uses_only_exposed_names(upskill_state):
    """View renames and hidden fields must survive combinator-based schemas."""
    proxy = await _proxy_for_state(
        upskill_state,
        view_tool={
            "parameters": {
                "to_source": {"rename": "destination"},
                "skill_name": {"hidden": True},
            }
        },
    )
    search, describe, call = await _meta_tools(proxy)
    searched = await search.fn(query="promote", include_schema=True)
    described = await describe.fn(tool_name="promote_skill_draft")
    for metadata in (searched["tools"][0], described):
        assert "destination" in metadata["accepted_parameter_names"]
        assert "to_source" not in metadata["accepted_parameter_names"]
        assert "skill_name" not in metadata["accepted_parameter_names"]
        serialized = json.dumps(metadata)
        assert '"to_source"' not in serialized
        assert '"skill_name"' not in serialized

    direct_proxy = await _proxy_for_state(upskill_state)
    _, _, direct_call = await _meta_tools(direct_proxy)
    await _call(direct_call, "create_skill_draft", {"skill_name": "renamed-e2e"})

    preview = await _call(
        call,
        "promote_skill_draft",
        {
            "draft_id": "draft:renamed-e2e",
            "destination": "personal",
            "dry_run": True,
        },
    )
    assert preview["dry_run"] is True
    assert not (upskill_state["source"] / "renamed-e2e").exists()

    applied = await _call(
        call,
        "promote_skill_draft",
        {
            "draft_id": "draft:renamed-e2e",
            "destination": "personal",
            "dry_run": False,
        },
    )
    assert applied["applied"] is True
    assert (upskill_state["source"] / "renamed-e2e" / "SKILL.md").exists()


async def test_old_proxy_new_upskill_and_new_proxy_old_upskill(upskill_state):
    """Both staggered deployment orders retain their documented capabilities."""
    transport = StdioTransport(
        command=str(upskill_state["binary"]),
        args=["mcp"],
        env={
            "UPSKILL_HOME": str(upskill_state["home"]),
            "UPSKILL_CONFIG": str(upskill_state["config"]),
        },
        cwd=str(UPSKILL_REPO),
    )
    async with Client(transport=transport) as legacy_passthrough:
        tools = await legacy_passthrough.list_tools()
        old_search_shape = [
            {"name": tool.name, "description": tool.description} for tool in tools
        ]
        assert all("inputSchema" not in item for item in old_search_shape)
        invalid = await legacy_passthrough.call_tool(
            "promote_skill_draft",
            {"draft_id": "draft:missing", "destination": "personal"},
            raise_on_error=False,
        )
        upstream_error = json.loads(invalid.content[0].text)
        assert upstream_error["error"] == "invalid_tool_arguments"
        assert upstream_error["did_you_mean"] == {"destination": "to_source"}

    legacy_server = Path(__file__).parent / "fixtures" / "legacy_upskill_server.py"
    proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={
                "skills": {
                    "command": sys.executable,
                    "args": [str(legacy_server)],
                }
            },
            tool_views={
                "skills": {"exposure_mode": "search_per_server", "include_all": True}
            },
        )
    )
    await proxy.initialize()
    search, describe, call = await _meta_tools(proxy)
    found = await search.fn(query="promote", include_schema=True)
    assert found["tools"][0]["name"] == "promote_skill_draft"
    assert (await describe.fn(tool_name="promote_skill_draft"))["inputSchema"]
    with pytest.raises(ToolArgumentValidationError):
        await call.fn(
            tool_name="promote_skill_draft", arguments={"destination": "personal"}
        )
    legacy_result = await _call(
        call,
        "promote_skill_draft",
        {"draft_id": "draft:legacy", "to_source": "personal", "dry_run": True},
    )
    assert legacy_result == {
        "draft_id": "draft:legacy",
        "destination": "personal",
        "dry_run": True,
    }


async def test_hosted_fixture_smoke_registry_hash_and_version(upskill_state):
    """The hosted stdio fixture exposes the expected identity and stable registry."""
    transport = StdioTransport(
        command=str(upskill_state["binary"]),
        args=["mcp"],
        env={
            "UPSKILL_HOME": str(upskill_state["home"]),
            "UPSKILL_CONFIG": str(upskill_state["config"]),
        },
        cwd=str(UPSKILL_REPO),
    )
    async with Client(transport=transport) as client:
        assert client.initialize_result.serverInfo.name == "upskill"
        assert client.initialize_result.serverInfo.version == "0.1.0"
        upstream_tool_count = len(await client.list_tools())

    proxy = await _proxy_for_state(upskill_state)
    snapshot = proxy.get_registry_snapshot("skills")
    assert snapshot["tool_count"] == upstream_tool_count
    encoded = json.dumps(
        [
            {"name": item["name"], "inputSchema": item["inputSchema"]}
            for item in snapshot["tools"]
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert snapshot["schema_hash"] == hashlib.sha256(encoded).hexdigest()
    _, describe, _ = await _meta_tools(proxy)
    response = await describe.fn(tool_name="promote_skill_draft")
    assert response["description"].startswith("Copy a draft")
