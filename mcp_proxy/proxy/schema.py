"""Schema transformation functions for MCP Proxy."""

import copy
from typing import Any, Callable

from fastmcp.server.tasks.config import TaskConfig
from fastmcp.tools.tool import FunctionTool

from mcp_proxy.models import ToolConfig


def resolve_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve $ref references in a JSON Schema to create a flat schema.

    This is important because some LLM clients don't properly handle
    $ref references in tool schemas. This function inlines all
    references to make the schema self-contained.

    Args:
        schema: JSON Schema that may contain $ref references

    Returns:
        A new schema with all $ref references resolved inline
    """
    if not schema:
        return schema

    # Deep copy to avoid mutating the original
    schema = copy.deepcopy(schema)

    # Get definitions (could be under $defs or definitions)
    defs = schema.get("$defs", schema.get("definitions", {}))

    def resolve_ref(obj: Any) -> Any:
        """Recursively resolve $ref references."""
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                # Handle local references like "#/$defs/SomeType"
                if ref.startswith("#/$defs/") or ref.startswith("#/definitions/"):
                    ref_name = ref.split("/")[-1]
                    if ref_name in defs:
                        # Replace the $ref with the actual definition
                        resolved = copy.deepcopy(defs[ref_name])
                        # Merge other properties from original (like description)
                        for key, value in obj.items():
                            if key != "$ref":
                                resolved[key] = value
                        return resolve_ref(resolved)  # Recursively resolve nested refs
                # If we can't resolve, return as-is
                return obj
            else:
                # Recursively process all values
                return {k: resolve_ref(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [resolve_ref(item) for item in obj]
        else:
            return obj

    # Resolve all references
    resolved = resolve_ref(schema)

    # Remove the $defs/definitions since they're now inlined
    resolved.pop("$defs", None)
    resolved.pop("definitions", None)

    return resolved


def create_tool_with_schema(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    fn: Callable[..., Any],
) -> FunctionTool:
    """Create a FastMCP FunctionTool with a custom input schema.

    Args:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for tool inputs
        fn: The wrapper function to call

    Returns:
        A FunctionTool instance with the custom schema
    """
    return FunctionTool(
        name=name,
        description=description,
        fn=fn,
        parameters=input_schema,
        enabled=True,
        tags=set(),
        task_config=TaskConfig(),
    )


def transform_schema(
    schema: dict[str, Any] | None,
    tool_config: ToolConfig | None,
) -> dict[str, Any] | None:
    """Transform an input schema based on parameter configuration.

    Handles:
    - Hiding parameters (removes from schema)
    - Renaming parameters (changes property name)
    - Overriding parameter descriptions
    - Setting default values (makes parameter optional)

    Args:
        schema: Original JSON Schema for tool inputs
        tool_config: Tool configuration with parameter overrides

    Returns:
        Transformed schema, or original if no changes needed
    """
    if schema is None or tool_config is None or not tool_config.parameters:
        return schema

    # Deep copy to avoid mutating the original
    new_schema = copy.deepcopy(schema)

    properties = new_schema.get("properties", {})
    required = new_schema.get("required", [])

    for param_name, param_config in tool_config.parameters.items():
        if param_name not in properties:
            continue

        if param_config.hidden:
            # Remove hidden parameter from schema
            del properties[param_name]
            if param_name in required:
                required.remove(param_name)
        elif param_config.rename:
            # Rename the parameter
            prop_value = properties.pop(param_name)
            if param_config.description:
                prop_value["description"] = param_config.description
            if param_config.default is not None:
                prop_value["default"] = param_config.default
            properties[param_config.rename] = prop_value
            if param_name in required:
                required.remove(param_name)
                # If there's a default, don't add to required
                if param_config.default is None:
                    required.append(param_config.rename)
        else:
            # Update description and/or default without renaming
            if param_config.description:
                properties[param_name]["description"] = param_config.description
            if param_config.default is not None:
                properties[param_name]["default"] = param_config.default
                # Remove from required if we have a default
                if param_name in required:
                    required.remove(param_name)

    new_schema["properties"] = properties
    new_schema["required"] = required

    return new_schema


def transform_args(
    args: dict[str, Any],
    parameter_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Transform arguments based on parameter configuration.

    Handles:
    - Injecting default values for hidden parameters
    - Injecting default values for missing optional parameters
    - Mapping renamed parameters back to original names

    Args:
        args: Arguments as passed by the caller (using exposed param names)
        parameter_config: Dict mapping original param names to their config

    Returns:
        Transformed arguments ready for the upstream tool
    """
    if parameter_config is None:
        return args

    new_args = dict(args)

    for param_name, config in parameter_config.items():
        if config.get("hidden"):
            # Inject default value for hidden parameter
            if config.get("default") is not None:
                new_args[param_name] = config["default"]
        elif config.get("rename"):
            # Map renamed parameter back to original name
            renamed = config["rename"]
            if renamed in new_args:
                new_args[param_name] = new_args.pop(renamed)
            elif config.get("default") is not None and param_name not in new_args:
                # Inject default if renamed param not provided
                new_args[param_name] = config["default"]
        elif config.get("default") is not None and param_name not in new_args:
            # Inject default for non-renamed optional param
            new_args[param_name] = config["default"]

    return new_args
