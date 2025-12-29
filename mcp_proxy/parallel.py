"""Parallel/fan-out tool execution."""

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class ParallelStep:
    """A single step in a parallel tool execution."""

    name: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParallelTool:
    """A tool that executes multiple upstream tools in parallel."""

    name: str
    description: str
    inputs: dict[str, Any]
    parallel_steps: list[ParallelStep]
    _call_tool_fn: Callable[..., Coroutine[Any, Any, Any]] | None = None

    @classmethod
    def from_config(cls, name: str, config: dict[str, Any]) -> "ParallelTool":
        """Create a ParallelTool from a config dict."""
        steps = []
        for step_name, step_config in config.get("parallel", {}).items():
            steps.append(
                ParallelStep(
                    name=step_name,
                    tool=step_config["tool"],
                    args=step_config.get("args", {}),
                )
            )

        return cls(
            name=name,
            description=config.get("description", ""),
            inputs=config.get("inputs", {}),
            parallel_steps=steps,
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        """Generate JSON schema from inputs config."""
        properties = {}
        required = []

        for input_name, input_config in self.inputs.items():
            properties[input_name] = {"type": input_config.get("type", "string")}
            if input_config.get("required", False):
                required.append(input_name)

        return {"properties": properties, "required": required}

    def _resolve_template(self, value: Any, inputs: dict[str, Any]) -> Any:
        """Resolve {inputs.X} templates in a value."""
        if (
            isinstance(value, str)
            and value.startswith("{inputs.")
            and value.endswith("}")
        ):
            input_name = value[8:-1]  # Extract name from {inputs.X}
            return inputs.get(input_name, value)
        return value

    def _resolve_args(
        self, args: dict[str, Any], inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve all templates in args dict."""
        return {k: self._resolve_template(v, inputs) for k, v in args.items()}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute all parallel steps concurrently."""
        import asyncio

        if self._call_tool_fn is None:
            raise RuntimeError("No call_tool_fn configured")

        async def run_step(step: ParallelStep) -> tuple[str, Any]:
            try:
                resolved_args = self._resolve_args(step.args, inputs)
                result = await self._call_tool_fn(step.tool, **resolved_args)
                return step.name, result
            except Exception as e:
                return step.name, {"error": str(e)}

        tasks = [run_step(step) for step in self.parallel_steps]
        results = await asyncio.gather(*tasks)

        return dict(results)
