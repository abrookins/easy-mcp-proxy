"""Artifact storage mixin."""

from typing import TYPE_CHECKING

from mcp_memory.models import Artifact

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class ArtifactStorageMixin:
    """Mixin for artifact-related storage operations."""

    def load_artifact(self: "BaseStorage", artifact_id: str) -> Artifact | None:
        """Load an artifact by ID."""
        return self._load_by_id("Artifact", "artifact_id", artifact_id, Artifact)

    def load_artifact_by_name(self: "BaseStorage", name: str) -> Artifact | None:
        """Load an artifact by name."""
        dir_path = self._get_dir("Artifact")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        file_path = dir_path / f"{safe_name}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Artifact, "content")

    def list_artifacts(
        self: "BaseStorage", project_id: str | None = None
    ) -> list[Artifact]:
        """List all artifacts, optionally filtered by project."""
        return self._list_markdown_files("Artifact", Artifact, "content", project_id)
