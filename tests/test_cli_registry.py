"""CLI coverage for canonical raw and exposed tool metadata."""

import json
from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

from mcp_proxy.cli import main
from mcp_proxy.cli.commands import _output_tool_schema
from mcp_proxy.proxy import MCPProxy


def _write_config(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
mcp_servers:
  skills:
    command: upskill
tool_views:
  catalog:
    tools:
      skills:
        zeta: {}
        promote_skill_draft:
          name: publish_skill
          description: "Publish: {original}"
          parameters:
            destination:
              rename: to_source
            secret:
              hidden: true
              default: fixed
        alpha: {}
""".strip()
        + "\n"
    )
    return config_file


def _upstream_tools():
    promote = MagicMock()
    promote.name = "promote_skill_draft"
    promote.description = "Promote a skill draft"
    promote.inputSchema = {
        "type": "object",
        "properties": {
            "destination": {"type": "string"},
            "dry_run": {"type": "boolean"},
            "secret": {"type": "string"},
        },
        "required": ["destination", "secret"],
    }
    alpha = MagicMock()
    alpha.name = "alpha"
    alpha.description = "First"
    alpha.inputSchema = {"type": "object", "properties": {}}
    zeta = MagicMock()
    zeta.name = "zeta"
    zeta.description = "Last"
    zeta.inputSchema = {"type": "object", "properties": {}}
    return [zeta, promote, alpha]


def _mock_upstream(monkeypatch, tools=None, error=None):
    async def create_client(self, server_name):
        if error is not None:
            raise error
        client = MagicMock()
        client.list_tools = AsyncMock(return_value=tools or _upstream_tools())
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        return client

    monkeypatch.setattr(MCPProxy, "_create_client", create_client)


def test_schema_keeps_raw_upstream_metadata(tmp_path, monkeypatch):
    """Unqualified view inspection must not replace raw SERVER.TOOL output."""
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main, ["schema", "skills.promote_skill_draft", "--json", "-c", str(config)]
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    properties = payload["schema"]["inputSchema"]["properties"]
    assert sorted(properties) == ["destination", "dry_run", "secret"]


def test_schema_view_json_uses_exposed_metadata(tmp_path, monkeypatch):
    """Canonical JSON reflects renames and never serializes hidden parameters."""
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main,
        ["schema", "--view", "catalog", "publish_skill", "--json", "-c", str(config)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "publish_skill"
    assert payload["original_name"] == "promote_skill_draft"
    assert payload["description"] == "Publish: Promote a skill draft"
    assert payload["accepted_parameter_names"] == ["dry_run", "to_source"]
    assert payload["supports_dry_run"] is True
    properties = payload["inputSchema"]["properties"]
    assert "secret" not in properties
    assert "destination" not in properties
    assert properties["to_source"]["type"] == "string"


def test_schema_view_human_summarizes_parameters_and_preview(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main, ["schema", "-v", "catalog", "publish_skill", "-c", str(config)]
    )

    assert result.exit_code == 0
    assert "Accepted parameters: dry_run, to_source" in result.output
    assert "Dry-run supported: yes" in result.output
    assert "secret" not in result.output


def test_schema_view_lists_tools_in_stable_order(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main, ["schema", "--view", "catalog", "--json", "-c", str(config)]
    )

    assert result.exit_code == 0
    assert [item["name"] for item in json.loads(result.output)["tools"]] == [
        "alpha",
        "publish_skill",
        "zeta",
    ]


def test_tools_view_verbose_json_and_server_filter(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "--view",
            "catalog",
            "--server",
            "skills",
            "--verbose",
            "--json",
            "-c",
            str(config),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["view"] == "catalog"
    assert [item["name"] for item in payload["tools"]] == [
        "alpha",
        "publish_skill",
        "zeta",
    ]
    assert all("inputSchema" in item for item in payload["tools"])


def test_tools_json_without_verbose_omits_full_schema(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)

    result = CliRunner().invoke(
        main, ["tools", "--view", "catalog", "--json", "-c", str(config)]
    )

    assert result.exit_code == 0
    assert all("inputSchema" not in item for item in json.loads(result.output)["tools"])


def test_schema_rejects_view_and_server_combination(tmp_path):
    config = _write_config(tmp_path)

    result = CliRunner().invoke(
        main,
        ["schema", "--view", "catalog", "--server", "skills", "-c", str(config)],
    )

    assert result.exit_code == 1
    assert "cannot be used together" in result.output


def test_missing_view_and_tool_include_suggestions(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)
    runner = CliRunner()

    missing_view = runner.invoke(
        main, ["schema", "--view", "catlog", "--json", "-c", str(config)]
    )
    missing_tool = runner.invoke(
        main,
        ["schema", "--view", "catalog", "publish_skil", "--json", "-c", str(config)],
    )

    assert missing_view.exit_code == 1
    assert json.loads(missing_view.output)["did_you_mean"] == "catalog"
    assert missing_tool.exit_code == 1
    assert json.loads(missing_tool.output)["did_you_mean"] == "publish_skill"


def test_connection_failure_is_distinct_from_not_found(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch, error=ConnectionError("offline"))

    result = CliRunner().invoke(
        main,
        ["schema", "--view", "catalog", "publish_skill", "--json", "-c", str(config)],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == "connection_error"
    assert payload["servers"] == {"skills": "offline"}


def test_default_tools_output_remains_configuration_only_and_sorted(tmp_path):
    config = _write_config(tmp_path)

    result = CliRunner().invoke(main, ["tools", "-c", str(config)])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "skills.alpha",
        "skills.promote_skill_draft",
        "skills.zeta",
    ]


def test_tools_human_views_server_filter_and_connection_errors(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)
    runner = CliRunner()

    concise = runner.invoke(main, ["tools", "--view", "catalog", "-c", str(config)])
    verbose = runner.invoke(
        main, ["tools", "--view", "catalog", "--verbose", "-c", str(config)]
    )
    by_server = runner.invoke(
        main, ["tools", "--server", "skills", "--json", "-c", str(config)]
    )

    assert concise.exit_code == verbose.exit_code == by_server.exit_code == 0
    assert concise.output.splitlines() == [
        "skills.alpha",
        "skills.publish_skill",
        "skills.zeta",
    ]
    assert "Tool: publish_skill" in verbose.output
    assert "Input schema:" in verbose.output
    assert len(json.loads(by_server.output)["tools"]) == 3

    _mock_upstream(monkeypatch, error=ConnectionError("offline"))
    failed = runner.invoke(main, ["tools", "--verbose", "--json", "-c", str(config)])
    assert failed.exit_code == 1
    assert json.loads(failed.output)["error"] == "connection_error"


def test_schema_human_lists_and_lookup_errors_cover_hint_variants(
    tmp_path, monkeypatch
):
    config = _write_config(tmp_path)
    _mock_upstream(monkeypatch)
    runner = CliRunner()

    listed = runner.invoke(main, ["schema", "--view", "catalog", "-c", str(config)])
    human_view_hint = runner.invoke(
        main, ["schema", "--view", "catlog", "-c", str(config)]
    )
    weak_view_tool = runner.invoke(
        main,
        ["schema", "--view", "catalog", "unrelated", "--json", "-c", str(config)],
    )
    raw_json_missing = runner.invoke(
        main, ["schema", "skills.unknown", "--json", "-c", str(config)]
    )
    raw_human_missing = runner.invoke(
        main, ["schema", "skills.unknown", "-c", str(config)]
    )
    raw_hint = runner.invoke(
        main, ["schema", "skills.alph", "--json", "-c", str(config)]
    )

    assert listed.exit_code == 0
    assert "Tool: publish_skill" in listed.output
    assert "Input schema:" not in listed.output
    assert human_view_hint.exit_code == 1
    assert "Did you mean 'catalog'?" in human_view_hint.output
    assert weak_view_tool.exit_code == 1
    assert "did_you_mean" not in json.loads(weak_view_tool.output)
    assert raw_json_missing.exit_code == raw_human_missing.exit_code == 1
    assert json.loads(raw_json_missing.output)["error_code"] == "unknown_tool"
    assert "not found on server 'skills'" in raw_human_missing.output
    assert json.loads(raw_hint.output)["did_you_mean"] == "alpha"


def test_legacy_schema_output_helper_preserves_not_found_shapes(capsys):
    """The compatibility helper retains both historical not-found renderings."""
    _output_tool_schema("skills.missing", None, as_json=True)
    assert json.loads(capsys.readouterr().out)["error"] == "not found"

    _output_tool_schema("skills.missing", None, as_json=False)
    assert (
        capsys.readouterr().out.strip() == "Tool 'missing' not found on server 'skills'"
    )
