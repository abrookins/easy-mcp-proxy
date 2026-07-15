"""Validation of search-mode calls against canonical exposed schemas."""

import json
import re
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for
from rapidfuzz import fuzz, process

from .schema import _camel_to_snake, normalize_dict_arguments
from .search_tools import TOOL_SUGGESTION_THRESHOLD
from .tool_info import ToolInfo

COMMON_PARAMETER_ALIASES = {
    "destination": ("to_source", "to_path"),
}


class ToolArgumentValidationError(ValueError):
    """Versioned, value-free validation failure for a known tool."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__(json.dumps(payload, sort_keys=True))


def _base_payload(tool: ToolInfo, message: str) -> dict[str, Any]:
    """Build fields required on every known-tool validation error."""
    return {
        "schema_version": 1,
        "error": "invalid_tool_arguments",
        "message": message,
        "tool": tool.name,
        "validation_path": [],
        "accepted_parameter_names": tool.accepted_parameter_names,
        "inputSchema": tool.to_metadata()["inputSchema"],
    }


def _normalize_aliases(tool: ToolInfo, arguments: dict[str, Any]) -> dict[str, Any]:
    """Map safe camelCase aliases and reject conflicting duplicate forms."""
    schema = tool.input_schema or {}
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return arguments

    normalized = dict(arguments)
    for argument_name in list(arguments):
        if argument_name in properties:
            continue
        schema_name = _camel_to_snake(argument_name)
        if schema_name == argument_name or schema_name not in properties:
            continue

        if schema_name in normalized:
            if normalized[schema_name] != normalized[argument_name]:
                raise ToolArgumentValidationError(
                    _base_payload(
                        tool,
                        (f'conflicting aliases "{argument_name}" and "{schema_name}"'),
                    )
                )
            normalized.pop(argument_name)
        else:
            normalized[schema_name] = normalized.pop(argument_name)

    return normalized


def _unknown_names(error: ValidationError) -> list[str]:
    """Derive additional-property names without rendering their values."""
    if error.validator != "additionalProperties" or not isinstance(
        error.instance, dict
    ):
        return []
    properties = error.schema.get("properties", {})
    patterns = tuple(error.schema.get("patternProperties", {}))
    return sorted(
        key
        for key in error.instance
        if key not in properties
        and not any(re.search(pattern, key) for pattern in patterns)
    )


def _safe_error_message(error: ValidationError, unknown: list[str]) -> str:
    """Describe a schema failure without interpolating caller values."""
    path = "/".join(str(part) for part in error.absolute_path)
    location = f' at "{path}"' if path else ""
    if error.validator == "required":
        missing = sorted(set(error.validator_value) - set(error.instance))
        name = missing[0] if missing else "required"
        return f'required parameter "{name}" is missing{location}'
    if error.validator == "additionalProperties" and unknown:
        joined = ", ".join(f'"{name}"' for name in unknown)
        return f"unknown parameter(s) {joined}{location}"
    if error.validator == "type":
        return f"invalid type{location}; expected {error.validator_value}"
    if error.validator == "enum":
        return f"value{location} is not one of the allowed enum choices"
    if error.validator in {"oneOf", "anyOf", "allOf"}:
        return f"value{location} does not satisfy {error.validator}"
    return f"arguments do not satisfy {error.validator}{location}"


def _validation_payload(tool: ToolInfo, error: ValidationError) -> dict[str, Any]:
    """Translate a jsonschema error to the stable public contract."""
    unknown = _unknown_names(error)
    payload = _base_payload(tool, _safe_error_message(error, unknown))
    payload["validation_path"] = list(error.absolute_path)
    if unknown:
        payload["unknown_parameter_names"] = unknown
        suggestions: dict[str, str] = {}
        for name in unknown:
            preferred = next(
                (
                    candidate
                    for candidate in COMMON_PARAMETER_ALIASES.get(name, ())
                    if candidate in tool.accepted_parameter_names
                ),
                None,
            )
            if preferred is not None:
                suggestions[name] = preferred
                continue
            match = process.extractOne(
                name, tool.accepted_parameter_names, scorer=fuzz.ratio
            )
            if match is not None and match[1] >= TOOL_SUGGESTION_THRESHOLD:
                suggestions[name] = match[0]
        if suggestions:
            payload["did_you_mean"] = suggestions
    return payload


def normalize_and_validate_arguments(
    tool: ToolInfo, arguments: dict[str, Any] | str | None
) -> dict[str, Any]:
    """Parse, normalize, and validate arguments against the exposed schema."""
    try:
        parsed = normalize_dict_arguments(arguments)
    except (TypeError, ValueError) as exc:
        raise ToolArgumentValidationError(
            _base_payload(tool, "arguments must be a JSON object")
        ) from exc

    normalized = _normalize_aliases(tool, parsed)
    if not tool.input_schema:
        return normalized

    validator_class = validator_for(tool.input_schema)
    validator_class.check_schema(tool.input_schema)
    errors = sorted(
        validator_class(tool.input_schema).iter_errors(normalized),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
        ),
    )
    if errors:
        raise ToolArgumentValidationError(_validation_payload(tool, errors[0]))
    return normalized
