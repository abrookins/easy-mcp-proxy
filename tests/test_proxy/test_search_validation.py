"""Validation tests for search-mode call wrappers."""

import json
from unittest.mock import AsyncMock

import pytest

from mcp_proxy.models import ToolViewConfig
from mcp_proxy.proxy import ToolInfo, ToolRegistry
from mcp_proxy.proxy.search_tools import create_call_tool_wrapper
from mcp_proxy.proxy.validation import ToolArgumentValidationError
from mcp_proxy.views import ToolView


def _wrapper(schema: dict, view: AsyncMock | None = None):
    tool = ToolInfo(
        name="mutate",
        server="skills",
        input_schema=schema,
    )
    registry = ToolRegistry([tool])
    target = view or AsyncMock()
    target.call_tool.return_value = {"ok": True}
    return create_call_tool_wrapper(target, registry, "skills_search_tools"), target


@pytest.mark.parametrize(
    ("schema", "arguments"),
    [
        (
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            {},
        ),
        (
            {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
            },
            {"count": "wrong"},
        ),
        (
            {
                "type": "object",
                "properties": {"mode": {"enum": ["safe", "fast"]}},
            },
            {"mode": "wrong"},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"enabled": {"type": "boolean"}},
                    }
                },
            },
            {"nested": {"enabled": "wrong"}},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"type": "integer"}}
                },
            },
            {"items": [1, "wrong"]},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "choice": {"oneOf": [{"type": "string"}, {"type": "number"}]}
                },
            },
            {"choice": False},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "choice": {"anyOf": [{"type": "string"}, {"type": "number"}]}
                },
            },
            {"choice": False},
        ),
        (
            {
                "type": "object",
                "properties": {
                    "count": {
                        "allOf": [
                            {"type": "integer"},
                            {"minimum": 1},
                            {"maximum": 3},
                        ]
                    }
                },
            },
            {"count": 10},
        ),
    ],
)
async def test_complete_json_schema_failures_are_rejected(schema, arguments):
    """The standards validator should enforce major JSON Schema constructs."""
    wrapper, view = _wrapper(schema)

    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper("mutate", arguments)

    assert exc_info.value.payload["error"] == "invalid_tool_arguments"
    view.call_tool.assert_not_awaited()


@pytest.mark.parametrize(
    ("additional", "arguments", "valid"),
    [
        (False, {"known": "ok", "extra": 1}, False),
        (True, {"known": "ok", "extra": 1}, True),
        (None, {"known": "ok", "extra": 1}, True),
        ({"type": "integer"}, {"known": "ok", "extra": 1}, True),
        ({"type": "integer"}, {"known": "ok", "extra": "wrong"}, False),
    ],
)
async def test_additional_properties_forms(additional, arguments, valid):
    """Unknown fields follow the exact additionalProperties contract."""
    schema = {
        "type": "object",
        "properties": {"known": {"type": "string"}},
    }
    if additional is not None:
        schema["additionalProperties"] = additional
    wrapper, view = _wrapper(schema)

    if valid:
        await wrapper("mutate", arguments)
        view.call_tool.assert_awaited_once()
    else:
        with pytest.raises(ToolArgumentValidationError):
            await wrapper("mutate", arguments)
        view.call_tool.assert_not_awaited()


async def test_camel_case_normalization_and_conflicting_values():
    """Safe aliases normalize once; conflicting duplicate forms are rejected."""
    schema = {
        "type": "object",
        "properties": {"pull_number": {"type": "integer"}},
        "required": ["pull_number"],
        "additionalProperties": False,
    }
    wrapper, view = _wrapper(schema)

    await wrapper("mutate", {"pullNumber": 7})
    assert view.call_tool.await_args.args[1] == {"pull_number": 7}

    view.reset_mock()
    await wrapper("mutate", {"pullNumber": 7, "pull_number": 7})
    assert view.call_tool.await_args.args[1] == {"pull_number": 7}

    view.reset_mock()
    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper("mutate", {"pullNumber": 8, "pull_number": 7})
    assert "conflicting aliases" in exc_info.value.payload["message"]
    view.call_tool.assert_not_awaited()


async def test_renamed_and_hidden_parameters_validate_then_transform_upstream():
    """Only exposed fields validate before upstream names and defaults are restored."""
    tool = ToolInfo(
        name="promote",
        server="skills",
        original_name="promote_skill_draft",
        input_schema={
            "type": "object",
            "properties": {"to_source": {"type": "string"}},
            "required": ["to_source"],
            "additionalProperties": False,
        },
        parameter_config={
            "destination": {"rename": "to_source"},
            "secret": {"hidden": True, "default": "fixed"},
        },
    )
    view = ToolView("catalog", ToolViewConfig())
    view.update_tool_mapping([tool])
    upstream = AsyncMock()
    upstream.__aenter__.return_value = upstream
    upstream.call_tool.return_value = {"ok": True}
    view._upstream_clients = {"skills": upstream}
    wrapper = create_call_tool_wrapper(
        view, ToolRegistry([tool]), "catalog_search_tools"
    )

    await wrapper("promote", {"to_source": "Obsidian"})

    upstream.call_tool.assert_awaited_once_with(
        "promote_skill_draft",
        {"destination": "Obsidian", "secret": "fixed"},
    )

    upstream.reset_mock()
    with pytest.raises(ToolArgumentValidationError):
        await wrapper("promote", {"destination": "Obsidian"})
    upstream.call_tool.assert_not_awaited()


async def test_valid_call_invokes_upstream_exactly_once():
    """Successful validation should forward one call with no duplicate execution."""
    wrapper, view = _wrapper(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )

    result = await wrapper("mutate", {"name": "valid"})

    assert result == {"ok": True}
    view.call_tool.assert_awaited_once()


async def test_destination_unknown_key_suggests_to_source_without_upstream_call():
    """The common promotion mistake should produce the actionable exposed name."""
    wrapper, view = _wrapper(
        {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "to_source": {"type": "string"},
            },
            "additionalProperties": False,
        }
    )

    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper("mutate", {"destination": "private"})

    assert exc_info.value.payload["did_you_mean"] == {"destination": "to_source"}
    view.call_tool.assert_not_awaited()


async def test_typo_unknown_key_uses_general_fuzzy_suggestion():
    """Non-special-case misspellings should use the conservative fuzzy matcher."""
    wrapper, view = _wrapper(
        {
            "type": "object",
            "properties": {"to_source": {"type": "string"}},
            "additionalProperties": False,
        }
    )

    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper("mutate", {"to_sorce": "private"})

    assert exc_info.value.payload["did_you_mean"] == {"to_sorce": "to_source"}
    view.call_tool.assert_not_awaited()


async def test_validation_errors_never_echo_argument_values():
    """Neither top-level nor nested caller values may appear in guidance."""
    wrapper, _ = _wrapper(
        {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        }
    )

    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper(
            "mutate",
            {
                "nested": {"count": "nested-secret", "token": "deep-secret"},
                "password": "top-secret",
            },
        )

    rendered = json.dumps(exc_info.value.payload)
    assert "nested-secret" not in rendered
    assert "deep-secret" not in rendered
    assert "top-secret" not in rendered


async def test_structured_upstream_errors_pass_through_unchanged():
    """The proxy should not wrap valid structured errors owned by Upskill."""
    upstream_error = ValueError(
        json.dumps(
            {
                "schema_version": 1,
                "error": "source_not_found",
                "message": "source not found",
            }
        )
    )
    view = AsyncMock()
    view.call_tool.side_effect = upstream_error
    wrapper, _ = _wrapper({"type": "object"}, view)

    with pytest.raises(ValueError) as exc_info:
        await wrapper("mutate", {})

    assert exc_info.value is upstream_error


async def test_domain_errors_are_not_mislabeled_as_schema_errors():
    """A valid call that fails in the domain must retain its original error type."""
    domain_error = RuntimeError("source not found")
    view = AsyncMock()
    view.call_tool.side_effect = domain_error
    wrapper, _ = _wrapper({"type": "object"}, view)

    with pytest.raises(RuntimeError, match="source not found") as exc_info:
        await wrapper("mutate", {})

    assert exc_info.value is domain_error


@pytest.mark.parametrize("arguments", ["{not-json", "[]", [], 7])
async def test_malformed_or_non_object_arguments_use_versioned_error(arguments):
    """Bad wrapper input should fail locally with the known tool's contract."""
    wrapper, view = _wrapper({"type": "object"})

    with pytest.raises(ToolArgumentValidationError) as exc_info:
        await wrapper("mutate", arguments)

    assert exc_info.value.payload["schema_version"] == 1
    assert exc_info.value.payload["tool"] == "mutate"
    assert exc_info.value.payload["inputSchema"] == {"type": "object"}
    view.call_tool.assert_not_awaited()
