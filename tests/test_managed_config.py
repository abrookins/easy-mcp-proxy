"""Shared management validation never executes candidate code."""

from unittest.mock import patch

import pytest

from mcp_proxy.identity import AccessDenied, Identity
from mcp_proxy.managed_config import (
    ConfigService,
    config_impact,
    materialize_config,
    seal_config,
    validate_managed_config,
)
from mcp_proxy.user_store import Conflict, NotFound, UserStore


@pytest.fixture
def managed(tmp_path):
    store = UserStore(tmp_path / "state")
    principals = []
    for user in ("operator", "user"):
        uid = store.provision("issuer", user, operator=user == "operator")
        store.grant(uid, "app", admin=True, views=["*"])
        principals.append(store.resolve(Identity("issuer", user, "app")))
    yield ConfigService(store), *principals
    store.close()


def activate(store, principal, revision):
    store.transition(principal, revision, "preparing")
    store.transition(principal, revision, "active")


def test_preview_redacts_and_retains_secret_references(managed):
    service, owner, other = managed
    config = {
        "mcp_servers": {
            "same": {"command": "echo", "args": ["credential"], "env": {"TOKEN": "key"}}
        },
        "tool_views": {"default": {"include_all": True}},
    }
    preview = service.preview(owner, None, config)
    assert "credential" not in str(preview)
    revision = preview["revision"]
    activate(service.store, owner, revision)
    read = service.read(owner)
    assert "credential" not in str(read["config"])
    assert service.revealed_args(owner) == {"same": ["credential"]}
    assert "$secret" in str(read["config"])
    assert materialize_config(service.store, owner, read["config"]) == config
    second = service.preview(owner, revision, read["config"])
    assert second["impact"]["mcp_servers"]["changed"] == []
    with pytest.raises(NotFound):
        service.preview(other, None, read["config"])
    with pytest.raises(Conflict):
        service.preview(owner, None, {})
    rollback = service.rollback_preview(owner, revision, revision)
    assert rollback["base"] == revision
    assert service.read(other)["revision"] is None


def test_host_privilege_independent_of_config_admin(managed):
    service, owner, other = managed
    for config in (
        {"mcp_servers": {"local": {"command": "cat", "args": ["/private"]}}},
        {"mcp_servers": {"metadata": {"url": "http://169.254.169.254/"}}},
        {"tool_views": {"default": {"hooks": {"pre_call": "evil.run"}}}},
        {"tool_views": {"default": {"custom_tools": [{"module": "evil.run"}]}}},
    ):
        with pytest.raises(AccessDenied, match="operator"):
            service.preview(other, None, config)
    # Pure structural validation must never load arbitrary Python.
    config = {"tool_views": {"default": {"hooks": {"pre_call": "evil.run"}}}}
    with patch("mcp_proxy.hooks.load_hook", side_effect=AssertionError("executed")):
        service.preview(owner, None, config)
    service.preview(other, None, {"tool_views": {"default": {"description": "mine"}}})


@pytest.mark.parametrize(
    "config",
    [
        {"unknown": "secret-marker"},
        {"mcp_servers": {"bad/name": {"command": "echo"}}},
        {"mcp_servers": {"both": {"url": "https://example.org", "command": "echo"}}},
        {"mcp_servers": {"neither": {}}},
        {"mcp_servers": {"bad": {"url": "file:///private"}}},
        {"mcp_servers": {"bad": {"url": "https:///missing-host"}}},
        {"mcp_servers": {"bad": {"url": "https://user:pass@example.org"}}},
        {"mcp_servers": {"bad": {"url": "https://example.org?token=secret"}}},
        {"mcp_servers": {"bad": {"url": "https://example.org/#fragment"}}},
        {"tool_views": {"_search": {}}},
        {"tool_views": {"bad/name": {}}},
        {"tool_views": {"default": {"exposure_mode": "invalid"}}},
        {"tool_views": {"default": {"tools": {"unknown": {}}}}},
        {"tool_views": {"default": {"include_all_servers": ["unknown"]}}},
        {"tool_views": {"default": {"exclude_servers": ["unknown"]}}},
        {"cache_secret": "secret"},
        {"cache_base_url": "https://example.org"},
        {"mcp_servers": {"x": {"command": "echo", "args": ["${HOST_SECRET}"]}}},
    ],
)
def test_invalid_configs_rejected_without_leaking_values(managed, config):
    service, owner, _ = managed
    with pytest.raises(ValueError) as exc:
        service.preview(owner, None, config)
    assert "secret-marker" not in str(exc.value)
    assert service.store.history(owner) == []


def test_valid_http_and_non_operator_view_edits(managed):
    service, owner, other = managed
    config = {"mcp_servers": {"remote": {"url": "https://example.org/mcp"}}}
    assert validate_managed_config(service.store, owner, config, {}).mcp_servers
    assert validate_managed_config(service.store, other, config, config).mcp_servers
    assert config_impact(
        {"tool_views": {"gone": {}, "changed": {}}},
        {"tool_views": {"new": {}, "changed": {"description": "updated"}}},
    )["tool_views"] == {"added": ["new"], "removed": ["gone"], "changed": ["changed"]}


def test_secret_shapes_types_and_revocation(managed):
    service, owner, other = managed
    value = {
        "mcp_servers": {
            "same": {"env": {"boolean": True, "null": None, "nested": [42]}}
        }
    }
    sealed = seal_config(service.store, owner, value)
    assert materialize_config(service.store, owner, sealed) == value
    assert seal_config(service.store, owner, sealed) == sealed
    for malformed in ({"$secret": "x", "extra": "y"}, {"$secret": 1}):
        for fn in (seal_config, materialize_config):
            with pytest.raises(ValueError, match="reference"):
                fn(service.store, owner, malformed)
    with pytest.raises(NotFound):
        materialize_config(service.store, other, sealed)
    secret_id = sealed["mcp_servers"]["same"]["env"]["boolean"]["$secret"]
    service.store.delete_secret(owner, secret_id)
    with pytest.raises(NotFound):
        materialize_config(service.store, owner, sealed)


def test_preview_bounds_and_secret_schema_locations(managed):
    from mcp_proxy.managed_config import _secret_path

    service, owner, _ = managed
    with pytest.raises(ValueError, match="1 MiB"):
        service.preview(owner, None, {"text": "x" * 1048576})
    assert _secret_path(("mcp_servers", "same", "env", "TOKEN"))
    assert _secret_path(
        (
            "tool_views",
            "work",
            "tools",
            "same",
            "echo",
            "parameters",
            "token",
            "default",
        )
    )
    assert _secret_path(
        (
            "tool_views",
            "work",
            "composite_tools",
            "both",
            "parallel",
            "one",
            "args",
            "token",
        )
    )
    for name in ("default", "args", "env", "headers"):
        assert not _secret_path(("tool_views", name, "description"))


def test_nested_unknown_settings_are_rejected(managed):
    service, owner, _ = managed
    with pytest.raises(ValueError, match="Invalid configuration structure"):
        service.preview(
            owner, None, {"tool_views": {"work": {"misspelled_option": True}}}
        )


def test_impact_shows_reviewable_fields_and_connection_replacements():
    previous = {
        "mcp_servers": {"same": {"command": "old", "tools": {}}},
        "tool_views": {"work": {"description": "before"}},
    }
    candidate = {
        "mcp_servers": {"same": {"command": "new", "tools": {}}},
        "tool_views": {"work": {"description": "after"}},
    }
    impact = config_impact(previous, candidate)
    assert impact["upstream_replacements"] == ["same"]
    assert {
        "path": ["tool_views", "work", "description"],
        "before": "before",
        "after": "after",
    } in impact["fields"]
    assert (
        len(
            config_impact(
                {"tool_views": {str(i): {"description": "old"} for i in range(250)}},
                {"tool_views": {str(i): {"description": "new"} for i in range(250)}},
            )["fields"]
        )
        == 200
    )
