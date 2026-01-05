"""Project storage mixin."""

from typing import TYPE_CHECKING

from mcp_memory.models import Project

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class ProjectStorageMixin:
    """Mixin for project-related storage operations."""

    def load_project(self: "BaseStorage", project_id: str) -> Project | None:
        """Load a project by ID."""
        return self._load_by_id("Project", "project_id", project_id, Project)

    def load_project_by_name(self: "BaseStorage", name: str) -> Project | None:
        """Load a project by name."""
        dir_path = self._get_dir("Project")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        file_path = dir_path / f"{safe_name}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Project, "instructions")

    def list_projects(self: "BaseStorage") -> list[Project]:
        """List all projects."""
        return self._list_markdown_files("Project", Project, "instructions", None)

