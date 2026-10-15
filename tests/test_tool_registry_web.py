"""API, security, accessibility, and UI tests for the live tool registry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_proxy.models import ProxyConfig
from mcp_proxy.proxy import MCPProxy
from mcp_proxy.web_ui import create_session_cookie, create_web_ui_routes


def _upstream_tool(
    name="promote_skill_draft",
    description="Promote a draft",
    schema=None,
):
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = schema or {
        "type": "object",
        "properties": {
            "destination": {"type": "string"},
            "dry_run": {"type": "boolean"},
            "secret": {"type": "string"},
        },
        "required": ["destination", "secret"],
    }
    return tool


def _proxy_with_registry(view_name="default"):
    config = ProxyConfig(
        mcp_servers={"skills": {"command": "echo"}},
        tool_views={
            view_name: {
                "exposure_mode": "search",
                "tools": {
                    "skills": {
                        "promote_skill_draft": {
                            "name": "publish_skill",
                            "parameters": {
                                "destination": {"rename": "to_source"},
                                "secret": {"hidden": True, "default": "fixed"},
                            },
                        }
                    }
                },
            }
        },
    )
    proxy = MCPProxy(config)
    proxy._upstream_tools["skills"] = [_upstream_tool()]
    proxy._refresh_tool_registries()
    return proxy


def _app(tmp_path, monkeypatch, proxy=None, auth_provider=None):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "mcp_servers": {"skills": {"command": "echo"}},
                "tool_views": {"default": {"description": "Default"}},
            }
        )
    )
    monkeypatch.setenv("MCP_PROXY_CONFIG", str(config_path))
    monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "test-secret")
    return Starlette(
        routes=create_web_ui_routes(
            path_prefix="/config", auth_provider=auth_provider, proxy=proxy
        )
    )


def test_registry_route_accepts_browser_session_and_bearer_token(tmp_path, monkeypatch):
    async def verify_token(token):
        return SimpleNamespace(claims={}) if token == "allowed" else None

    auth = MagicMock(verify_token=AsyncMock(side_effect=verify_token))
    app = _app(tmp_path, monkeypatch, _proxy_with_registry(), auth)
    client = TestClient(app)

    missing = client.get("/config/tools", headers={"Accept": "application/json"})
    bearer = client.get(
        "/config/tools",
        headers={"Accept": "application/json", "Authorization": "Bearer allowed"},
    )
    forbidden = client.get(
        "/config/tools",
        headers={"Accept": "application/json", "Authorization": "Bearer denied"},
    )
    client.cookies.set("mcp_proxy_session", create_session_cookie("operator"))
    browser_session = client.get(
        "/config/tools", headers={"Accept": "application/json"}
    )

    assert missing.status_code == 401
    assert bearer.status_code == 200
    assert forbidden.status_code == 401
    assert browser_session.status_code == 200


def test_registry_api_returns_only_canonical_exposed_metadata(tmp_path, monkeypatch):
    proxy = _proxy_with_registry()
    response = TestClient(_app(tmp_path, monkeypatch, proxy)).get("/config/tools")
    documented_response = TestClient(_app(tmp_path, monkeypatch, proxy)).get(
        "/config/api/tools"
    )

    assert response.status_code == 200
    assert documented_response.json() == response.json()
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["view"] == "default"
    assert payload["status"] == "ready"
    assert payload["tool_count"] == 1
    assert len(payload["schema_hash"]) == 64
    assert payload["snapshot_at"].endswith("Z")
    assert payload["generated_at"] == payload["snapshot_at"]
    tool = payload["tools"][0]
    assert tool["name"] == "publish_skill"
    assert tool["original_name"] == "promote_skill_draft"
    assert tool["accepted_parameter_names"] == ["dry_run", "to_source"]
    assert tool["supports_dry_run"] is True
    serialized = response.text
    assert "secret" not in serialized
    assert "destination" not in serialized


def test_registry_api_unknown_empty_warning_and_failure_states(tmp_path, monkeypatch):
    proxy = _proxy_with_registry("catalog")
    client = TestClient(_app(tmp_path, monkeypatch, proxy))

    unknown = client.get("/config/tools?view=catalg")
    assert unknown.status_code == 404
    assert unknown.json()["did_you_mean"] == "catalog"
    weak_unknown = client.get("/config/tools?view=unrelated")
    assert weak_unknown.status_code == 404
    assert "did_you_mean" not in weak_unknown.json()

    empty = MCPProxy(ProxyConfig())
    empty_payload = (
        TestClient(_app(tmp_path, monkeypatch, empty)).get("/config/tools").json()
    )
    assert empty_payload["status"] == "empty"
    assert empty_payload["tools"] == []

    proxy._registry_warnings.append("Snapshot is older than the last refresh.")
    warning = client.get("/config/tools?view=catalog").json()
    assert warning["status"] == "warning"
    assert warning["warnings"] == ["Snapshot is older than the last refresh."]

    failed = MCPProxy(ProxyConfig(mcp_servers={"skills": {"command": "missing"}}))
    failed._registry_upstream_errors["skills"] = "upstream connection unavailable"
    failure = (
        TestClient(_app(tmp_path, monkeypatch, failed)).get("/config/tools").json()
    )
    assert failure["status"] == "error"
    assert failure["upstream_errors"] == {"skills": "upstream connection unavailable"}


def test_registry_route_without_live_proxy_is_service_unavailable(
    tmp_path, monkeypatch
):
    response = TestClient(_app(tmp_path, monkeypatch)).get("/config/tools")
    assert response.status_code == 503
    assert response.json()["error"] == "registry_unavailable"


def test_upstream_html_is_returned_as_data_not_markup(tmp_path, monkeypatch):
    attack = '<script data-x="1">alert(1)</script>'
    schema_attack = '<img src=x onerror="alert(2)">'
    proxy = MCPProxy(
        ProxyConfig(
            mcp_servers={"skills": {"command": "echo"}},
            tool_views={"default": {"include_all": True}},
        )
    )
    proxy._upstream_tools["skills"] = [
        _upstream_tool(
            attack,
            attack,
            {
                "type": "object",
                "properties": {
                    "safe": {"type": "string", "description": schema_attack}
                },
            },
        )
    ]
    proxy._refresh_tool_registries()
    client = TestClient(_app(tmp_path, monkeypatch, proxy))

    page = client.get("/config").text
    assert attack not in page
    payload = client.get("/config/api/tools").json()
    assert payload["tools"][0]["name"] == attack
    script = client.get("/config/static/app.js").text
    assert "innerHTML" not in script
