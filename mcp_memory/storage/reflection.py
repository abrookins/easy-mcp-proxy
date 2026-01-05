"""Reflection storage mixin."""

from typing import TYPE_CHECKING

from mcp_memory.models import Reflection

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class ReflectionStorageMixin:
    """Mixin for reflection-related storage operations."""

    def load_reflection(self: "BaseStorage", reflection_id: str) -> Reflection | None:
        """Load a reflection by ID."""
        dir_path = self._get_dir("Reflection")
        file_path = dir_path / f"{reflection_id}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Reflection, "text")

    def list_reflections(
        self: "BaseStorage",
        project_id: str | None = None,
        skill_id: str | None = None,
    ) -> list[Reflection]:
        """List reflections, optionally filtered by project or skill."""
        dir_path = self._get_dir("Reflection")
        if not dir_path.exists():
            return []
        reflections = []
        for file_path in dir_path.glob("*.md"):
            obj = self._load_markdown_file(file_path, Reflection, "text")
            if obj:  # pragma: no branch
                if project_id and obj.project_id != project_id:
                    continue
                if skill_id and obj.skill_id != skill_id:
                    continue
                reflections.append(obj)
        return reflections
