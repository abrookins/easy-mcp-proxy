"""Skill storage mixin."""

from typing import TYPE_CHECKING

from mcp_memory.models import Skill

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class SkillStorageMixin:
    """Mixin for skill-related storage operations."""

    def load_skill(self: "BaseStorage", skill_id: str) -> Skill | None:
        """Load a skill by ID."""
        return self._load_by_id("Skill", "skill_id", skill_id, Skill)

    def list_skills(self: "BaseStorage") -> list[Skill]:
        """List all skills."""
        return self._list_markdown_files("Skill", Skill, "instructions", None)
