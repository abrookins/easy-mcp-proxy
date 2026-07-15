"""ToolInfo class for MCP Proxy."""

import copy
from typing import Any, TypedDict


class CanonicalToolMetadata(TypedDict):
    """Serialized metadata for a tool exactly as exposed by the proxy."""

    name: str
    description: str
    server: str
    original_name: str
    accepted_parameter_names: list[str]
    supports_dry_run: bool
    inputSchema: dict[str, Any]


class ToolInfo:
    """Canonical metadata for one tool as exposed by the proxy."""

    def __init__(
        self,
        name: str,
        description: str = "",
        server: str = "",
        input_schema: dict[str, Any] | None = None,
        original_name: str | None = None,
        parameter_config: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.server = server
        self.input_schema = input_schema
        # original_name is the upstream tool name if this tool was aliased
        self.original_name = original_name if original_name else name
        # parameter_config stores the ParameterConfig for each param
        # (for arg transformation)
        self.parameter_config = parameter_config

    @property
    def accepted_parameter_names(self) -> list[str]:
        """Return exposed parameter names in deterministic order."""
        if not self.input_schema:
            return []
        properties = self.input_schema.get("properties")
        if not isinstance(properties, dict):
            return []
        return sorted(properties)

    @property
    def supports_dry_run(self) -> bool:
        """Return whether the exposed schema advertises boolean dry_run."""
        if not self.input_schema:
            return False
        properties = self.input_schema.get("properties")
        if not isinstance(properties, dict):
            return False
        dry_run = properties.get("dry_run")
        return isinstance(dry_run, dict) and dry_run.get("type") == "boolean"

    def to_metadata(
        self, include_schema: bool = True
    ) -> CanonicalToolMetadata | dict[str, Any]:
        """Serialize canonical exposed metadata for MCP, CLI, or web output."""
        metadata: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "server": self.server,
            "original_name": self.original_name,
            "accepted_parameter_names": self.accepted_parameter_names,
            "supports_dry_run": self.supports_dry_run,
        }
        if include_schema:
            metadata["inputSchema"] = copy.deepcopy(self.input_schema or {})
        return metadata

    def __repr__(self) -> str:
        return f"ToolInfo(name={self.name!r}, server={self.server!r})"


class ToolRegistry:
    """Atomically replaceable snapshot of canonical exposed tool metadata."""

    def __init__(self, tools: list[ToolInfo] | tuple[ToolInfo, ...] = ()):
        self._snapshot: tuple[tuple[ToolInfo, ...], dict[str, ToolInfo]]
        self._snapshot = ((), {})
        self.replace(tools)

    def replace(self, tools: list[ToolInfo] | tuple[ToolInfo, ...]) -> None:
        """Replace the complete registry snapshot in one assignment."""
        snapshot = tuple(tools)
        by_name = {tool.name: tool for tool in snapshot}
        self._snapshot = (snapshot, by_name)

    @property
    def tools(self) -> tuple[ToolInfo, ...]:
        """Return the current immutable tool sequence."""
        return self._snapshot[0]

    def get(self, name: str) -> ToolInfo | None:
        """Look up one exposed tool by exact name."""
        return self._snapshot[1].get(name)

    def metadata(self, include_schema: bool = True) -> list[dict[str, Any]]:
        """Serialize all tools from one internally consistent snapshot."""
        tools = self._snapshot[0]
        return [tool.to_metadata(include_schema=include_schema) for tool in tools]

    def instructions(self, entity_name: str, exposure_mode: str) -> str:
        """Generate an authoritative human reference from the live snapshot."""
        tools = self._snapshot[0]
        lines = [
            f"# Exposed tool registry: {entity_name}",
            "",
            (
                "This section is generated from the live proxy registry and is "
                "authoritative for exposed tool names and parameters."
            ),
            "",
            f"Exposure mode: `{exposure_mode}`.",
            "",
        ]
        if exposure_mode == "search":
            lines.extend(
                [
                    (
                        f"Discover with `{entity_name}_search_tools`, inspect with "
                        f"`{entity_name}_describe_tool`, and invoke with "
                        f"`{entity_name}_call_tool`."
                    ),
                    "",
                ]
            )
        elif exposure_mode == "search_per_server":
            lines.extend(
                [
                    (
                        "Each upstream server exposes its own `*_search_tools`, "
                        "`*_describe_tool`, and `*_call_tool` helpers."
                    ),
                    "",
                ]
            )
        else:
            lines.extend(["Call the listed tools directly by exposed name.", ""])

        lines.extend(["## Tools", ""])
        if not tools:
            lines.append("No tools are currently exposed.")
        for tool in tools:
            parameters = ", ".join(
                f"`{name}`" for name in tool.accepted_parameter_names
            )
            if not parameters:
                parameters = "none"
            preview = " Dry-run preview supported." if tool.supports_dry_run else ""
            lines.append(
                f"- `{tool.name}`: {tool.description} "
                f"Accepted parameters: {parameters}.{preview}"
            )
        return "\n".join(lines).rstrip() + "\n"
