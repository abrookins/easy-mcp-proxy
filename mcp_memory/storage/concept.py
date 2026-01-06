"""Concept storage mixin."""

from pathlib import Path
from typing import TYPE_CHECKING

from mcp_memory.models import Concept
from mcp_memory.storage.base import parse_frontmatter

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class ConceptStorageMixin:
    """Mixin for concept-related storage operations."""

    def load_concept(self: "BaseStorage", concept_id: str) -> Concept | None:
        """Load a concept by ID (searches all concept files recursively)."""
        return self._load_by_id("Concept", "concept_id", concept_id, Concept)

    def find_concept_file(self: "BaseStorage", concept_id: str) -> Path | None:
        """Find the file path for a concept by its ID.

        Returns the path to the file containing the concept, or None if not found.
        Used when updating concepts to detect if the file needs to be moved.
        """
        base_dir = self._get_dir("Concept")
        if not base_dir.exists():
            return None

        for file_path in base_dir.glob("**/*.md"):
            content = file_path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)
            if frontmatter.get("concept_id") == concept_id:
                return file_path
        return None

    def delete_concept_file(self: "BaseStorage", file_path: Path) -> bool:
        """Delete a concept file at the given path.

        Returns True if the file was deleted, False if it didn't exist.
        Also cleans up empty parent directories.
        """
        if not file_path.exists():
            return False

        file_path.unlink()

        # Clean up empty parent directories up to the concepts base dir
        base_dir = self._get_dir("Concept")
        parent = file_path.parent
        while parent != base_dir and parent.exists():
            if not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            else:
                break

        return True

    def load_concept_by_name(self: "BaseStorage", name: str) -> Concept | None:
        """Load a concept by name (searches recursively, backward compatible).

        For hierarchical lookup, use load_concept_by_path() instead.
        """
        base_dir = self._get_dir("Concept")
        if not base_dir.exists():
            return None

        # Search all files recursively for matching name
        name_lower = name.lower()
        for file_path in base_dir.glob("**/*.md"):
            if file_path.stem.lower() == name_lower:
                return self._load_markdown_file(file_path, Concept, "text", base_dir)
            # Also check frontmatter name field
            content = file_path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)
            if frontmatter.get("name", "").lower() == name_lower:
                return self._load_markdown_file(file_path, Concept, "text", base_dir)
            # Check aliases (Obsidian feature)
            aliases = frontmatter.get("aliases", [])
            if isinstance(aliases, list) and any(
                a.lower() == name_lower for a in aliases
            ):
                return self._load_markdown_file(file_path, Concept, "text", base_dir)

        return None

    def load_concept_by_path(self: "BaseStorage", path: str) -> Concept | None:
        """Load a concept by its hierarchical path.

        Path format: "Parent/Child/Grandchild" or just "Name" for root concepts.
        Concepts are stored as Folder/Folder.md.

        Examples:
            - "Andrew Brookins" -> Concepts/Andrew Brookins/Andrew Brookins.md
            - "Parent/Child" -> Concepts/Parent/Child/Child.md
        """
        base_dir = self._get_dir("Concept")
        if not base_dir.exists():
            return None

        # Parse the path
        parts = path.split("/")
        safe_parts = [self._sanitize_name(p) for p in parts]
        concept_name = safe_parts[-1]

        # Concepts are stored as Folder/Folder.md
        folder_path = base_dir / "/".join(safe_parts)
        file_path = folder_path / f"{concept_name}.md"
        if file_path.exists():
            return self._load_markdown_file(file_path, Concept, "text", base_dir)

        # Try exact path without sanitization
        folder_path = base_dir / path
        file_path = folder_path / f"{parts[-1]}.md"
        if file_path.exists():
            return self._load_markdown_file(file_path, Concept, "text", base_dir)

        return None

    def list_concept_child_paths(
        self: "BaseStorage", parent_path: str | None = None
    ) -> list[str]:
        """List paths of direct children of a concept (no file I/O).

        Returns paths that can be used with read_concept_by_path().
        This is the most efficient way to discover children since it
        only examines directory/file names, not file contents.

        Args:
            parent_path: Path to parent (e.g., "Andrew Brookins"). None for root.

        Returns:
            List of child concept paths (e.g., ["Parent/Child1", "Parent/Child2"]).
        """
        base_dir = self._get_dir("Concept")
        if not base_dir.exists():
            return []

        if parent_path:
            safe_path = self._sanitize_path(parent_path)
            target_dir = base_dir / safe_path
        else:
            target_dir = base_dir

        if not target_dir.exists():
            return []

        # All concepts are stored as Folder/Folder.md
        child_names: list[str] = []
        for subdir in target_dir.iterdir():
            if subdir.is_dir() and (subdir / f"{subdir.name}.md").exists():
                child_names.append(subdir.name)

        # Build full paths
        if parent_path:
            return [f"{parent_path}/{name}" for name in sorted(child_names)]
        return sorted(child_names)

    def list_concept_children(
        self: "BaseStorage", parent_path: str | None = None
    ) -> list[Concept]:
        """List direct children of a concept path.

        Args:
            parent_path: Path to parent (e.g., "Andrew Brookins"). None for root.

        Returns:
            List of concepts that are direct children of the given path.

        Note: For just paths, use list_concept_child_paths() which is faster.
        """
        base_dir = self._get_dir("Concept")
        if not base_dir.exists():
            return []

        if parent_path:
            safe_path = self._sanitize_path(parent_path)
            target_dir = base_dir / safe_path
        else:
            target_dir = base_dir

        if not target_dir.exists():
            return []

        children = []

        # All concepts are stored as Folder/Folder.md
        for subdir in target_dir.iterdir():
            if subdir.is_dir():
                concept_file = subdir / f"{subdir.name}.md"
                if concept_file.exists():
                    concept = self._load_markdown_file(
                        concept_file, Concept, "text", base_dir
                    )
                    if concept:
                        children.append(concept)

        return children

    def get_concept_parent(self: "BaseStorage", path: str) -> Concept | None:
        """Get the parent concept of a given path.

        Args:
            path: Full path to concept (e.g., "Andrew Brookins/Preferences")

        Returns:
            Parent concept if it exists, None otherwise.
        """
        parts = path.split("/")
        if len(parts) <= 1:
            return None  # Root level, no parent

        parent_path = "/".join(parts[:-1])
        return self.load_concept_by_path(parent_path)

    def list_concepts(
        self: "BaseStorage",
        project_id: str | None = None,
        parent_path: str | None = None,
    ) -> list[Concept]:
        """List all concepts, optionally filtered by project or parent path.

        Args:
            project_id: Filter by project ID
            parent_path: Filter to concepts under this path (e.g., "Andrew Brookins")

        Also searches extra_concept_dirs if configured.
        """
        concepts = self._list_markdown_files("Concept", Concept, "text", project_id)

        # Also search extra concept directories recursively
        for extra_dir in self.config.extra_concept_dirs:
            extra_path = self.base_path / extra_dir
            if extra_path.exists():  # pragma: no branch
                for file_path in extra_path.glob("**/*.md"):
                    try:
                        obj = self._load_markdown_file(
                            file_path, Concept, "text", extra_path
                        )
                        if obj:  # pragma: no branch
                            if project_id and hasattr(obj, "project_id"):
                                if obj.project_id != project_id:
                                    continue
                            concepts.append(obj)
                    except Exception:
                        # Skip files that can't be parsed
                        pass

        # Filter by parent_path if specified
        if parent_path:
            safe_parent = parent_path.lower()
            concepts = [
                c
                for c in concepts
                if c.full_path.lower().startswith(safe_parent + "/")
                or c.full_path.lower() == safe_parent
            ]

        return concepts
