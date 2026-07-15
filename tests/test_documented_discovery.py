"""Keep the operator discovery documentation aligned with live exposure modes."""

import re
from pathlib import Path

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy
from tests.helpers import get_tool_names


async def test_documented_meta_tools_exist_in_all_exposure_modes():
    expected = {
        "direct": {"find_skills", "get_tool_instructions"},
        "search": {
            "catalog_search_tools",
            "catalog_describe_tool",
            "catalog_call_tool",
            "get_tool_instructions",
        },
        "search_per_server": {
            "skills_search_tools",
            "skills_describe_tool",
            "skills_call_tool",
            "get_tool_instructions",
        },
    }
    for mode, names in expected.items():
        proxy = MCPProxy(
            ProxyConfig(
                mcp_servers={"skills": {"command": "echo"}},
                tool_views={
                    "catalog": {
                        "exposure_mode": mode,
                        "tools": {"skills": {"find_skills": {}}},
                    }
                },
            )
        )
        assert set(await get_tool_names(proxy.get_view_mcp("catalog"))) == names


def test_feature_document_cli_examples_are_explicitly_environment_dependent():
    document = (Path("docs") / "tool-discovery.md").read_text()
    for line in document.splitlines():
        if line.startswith("mcp-proxy "):
            prefix = document[: document.index(line)].splitlines()[-1]
            assert "Environment-dependent" in prefix


def test_all_local_markdown_links_resolve():
    markdown_files = [Path("README.md"), *sorted(Path("docs").rglob("*.md"))]
    pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    missing = []
    for document in markdown_files:
        for target in pattern.findall(document.read_text()):
            if (
                "://" in target
                or target.startswith("#")
                or target.startswith("mailto:")
            ):
                continue
            path_text = target.split("#", 1)[0]
            if not path_text:
                continue
            resolved = (document.parent / path_text).resolve()
            if not resolved.exists():
                missing.append(f"{document}: {target}")
    assert missing == []


def test_rollbacks_are_documented_as_independent_and_state_preserving():
    document = (Path("docs") / "tool-discovery.md").read_text()
    prose = " ".join(document.split())

    assert "### Roll back Upskill independently" in document
    assert "### Roll back Easy MCP Proxy independently" in document
    assert "require no configuration or state migration" in prose
    assert "Do not delete drafts, sources, overlays, or installed skills" in prose
    assert "launchctl kickstart -k" in document
