"""Base storage class with core methods.

Handles reading/writing markdown files with YAML frontmatter.
"""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from mcp_memory.models import Concept, MemoryConfig

T = TypeVar("T", bound=BaseModel)

# Fields that go in the markdown body (not YAML frontmatter)
BODY_FIELDS = {
    "Thread": set(),  # Threads are pure YAML
    "Concept": {"text"},
    "Project": {"instructions"},
    "Skill": {"instructions"},
    "Reflection": {"text"},
    "Artifact": {"content"},
}

# Fields derived from file/directory structure (not stored in frontmatter)
DERIVED_FIELDS = {
    "Concept": {"parent_path"},  # Derived from directory structure
}


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and markdown body from content."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def extract_client_frontmatter(text: str) -> tuple[dict | None, str]:
    """Extract frontmatter from text content if present.

    Used to detect when clients submit content with their own frontmatter.
    Returns (client_frontmatter, remaining_body) or (None, original_text).
    """
    if not text.startswith("---"):
        return None, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text

    try:
        client_fm = yaml.safe_load(parts[1])
        if client_fm and isinstance(client_fm, dict):
            remaining = parts[2].strip()
            return client_fm, remaining
    except yaml.YAMLError:
        pass

    return None, text


def reconstruct_client_frontmatter(client_fm: dict, body: str) -> str:
    """Reconstruct body text with client frontmatter prepended.

    Used when loading content to return it in the same format the client sent.
    """
    yaml_str = yaml.dump(client_fm, default_flow_style=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n\n{body}"


def format_frontmatter(data: dict, body: str = "") -> str:
    """Format data as YAML frontmatter with optional markdown body."""
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    if body:
        return f"---\n{yaml_str}---\n\n{body}"
    return f"---\n{yaml_str}---\n"


class BaseStorage:
    """Base file-based storage for memory objects."""

    def __init__(self, config: MemoryConfig | None = None):
        self.config = config or MemoryConfig()
        self.base_path = Path(self.config.base_path)

    def _get_dir(self, model_type: str) -> Path:
        """Get the directory for a model type."""
        dirs = {
            "Thread": self.config.threads_dir,
            "Concept": self.config.concepts_dir,
            "Project": self.config.projects_dir,
            "Skill": self.config.skills_dir,
            "Reflection": self.config.reflections_dir,
            "Artifact": self.config.artifacts_dir,
        }
        return self.base_path / dirs[model_type]

    def _ensure_dir(self, model_type: str) -> Path:
        """Ensure directory exists and return it."""
        dir_path = self._get_dir(model_type)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name for use as a filename."""
        return "".join(c if c.isalnum() or c in " -_" else "_" for c in name)

    def _sanitize_path(self, path: str) -> str:
        """Sanitize a path (with slashes) for use as a directory path."""
        parts = path.split("/")
        return "/".join(self._sanitize_name(part) for part in parts)

    def _get_filename(self, obj: BaseModel) -> str:
        """Get filename for an object."""
        model_type = type(obj).__name__
        if model_type == "Thread":
            return f"{obj.thread_id}.yaml"
        elif model_type == "Concept":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Project":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Skill":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Artifact":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        else:  # Reflection
            return f"{obj.reflection_id}.md"

    def _get_concept_dir(self, concept: "Concept") -> Path:
        """Get the directory path for a concept based on its parent_path."""
        base_dir = self._get_dir("Concept")
        if concept.parent_path:
            safe_path = self._sanitize_path(concept.parent_path)
            return base_dir / safe_path
        return base_dir

    def _get_concept_file_path(self, concept: "Concept") -> Path:
        """Get the file path for a concept.

        Uses flat format (Name.md) by default.
        Uses folder format (Name/Name.md) only if a folder already exists
        for this concept (i.e., it has children).
        """
        parent_dir = self._get_concept_dir(concept)
        safe_name = self._sanitize_name(concept.name)

        # Check if a folder already exists for this concept
        folder_path = parent_dir / safe_name
        if folder_path.is_dir():
            # Folder exists (concept has children), use folder format
            return folder_path / f"{safe_name}.md"
        else:
            # No folder, use flat format
            return parent_dir / f"{safe_name}.md"

    def _promote_parent_to_folder(self, concept: "Concept") -> None:
        """Promote parent concept from flat to folder format if needed.

        When saving a child concept, the parent must be in folder format.
        If parent is currently flat (Parent.md), move it to Parent/Parent.md.
        """
        if not concept.parent_path:
            return

        # Get the immediate parent's name (last component of parent_path)
        parent_parts = concept.parent_path.split("/")
        immediate_parent_name = parent_parts[-1]
        safe_parent_name = self._sanitize_name(immediate_parent_name)

        # Get the grandparent directory (where the parent concept lives)
        concepts_dir = self._get_dir("Concept")
        if len(parent_parts) > 1:
            grandparent_path = "/".join(parent_parts[:-1])
            safe_grandparent = self._sanitize_path(grandparent_path)
            grandparent_dir = concepts_dir / safe_grandparent
        else:
            grandparent_dir = concepts_dir

        # Check if parent is in flat format
        flat_file = grandparent_dir / f"{safe_parent_name}.md"
        folder_path = grandparent_dir / safe_parent_name
        folder_file = folder_path / f"{safe_parent_name}.md"

        if flat_file.exists() and not folder_path.exists():
            # Parent is flat, promote to folder format
            folder_path.mkdir(parents=True, exist_ok=True)
            flat_file.rename(folder_file)

    def save(self, obj: BaseModel) -> Path:
        """Save an object to disk."""
        model_type = type(obj).__name__

        # Handle concept hierarchy specially
        if model_type == "Concept":
            # Promote parent to folder format if needed (for child concepts)
            self._promote_parent_to_folder(obj)
            file_path = self._get_concept_file_path(obj)
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            dir_path = self._ensure_dir(model_type)
            filename = self._get_filename(obj)
            file_path = dir_path / filename

        # Convert to dict
        data = obj.model_dump(mode="json")

        # Separate body fields from frontmatter
        body_field_names = BODY_FIELDS.get(model_type, set())
        derived_field_names = DERIVED_FIELDS.get(model_type, set())
        body_parts = []
        frontmatter = {}
        client_frontmatter = None

        for key, value in data.items():
            if key in body_field_names:
                if value:
                    # Check if body content has its own frontmatter
                    client_fm, remaining = extract_client_frontmatter(str(value))
                    if client_fm:
                        client_frontmatter = client_fm
                        body_parts.append(remaining)
                    else:
                        body_parts.append(str(value))
            elif key in derived_field_names:
                # Skip derived fields - they're reconstructed from file structure
                pass
            else:
                frontmatter[key] = value

        # Store client frontmatter under 'client' key if present
        if client_frontmatter:
            frontmatter["client"] = client_frontmatter

        body = "\n\n".join(body_parts)

        # Write file
        if model_type == "Thread":
            # Threads are pure YAML
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        else:
            content = format_frontmatter(frontmatter, body)

        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _load_markdown_file(
        self,
        file_path: Path,
        model_class: type[T],
        body_field: str,
        base_dir: Path | None = None,
    ) -> T | None:
        """Load a markdown file with frontmatter into a model.

        For Obsidian compatibility:
        - Derives 'name' from filename if not in frontmatter
        - Derives ID from filename if not in frontmatter
        - Allows extra frontmatter fields

        For Concept hierarchy:
        - Derives 'parent_path' from directory structure relative to base_dir

        For client frontmatter round-tripping:
        - If 'client' key exists, reconstructs body with client frontmatter
        """
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)

        # Reconstruct client frontmatter in body if present
        client_fm = frontmatter.pop("client", None)
        if client_fm and isinstance(client_fm, dict):
            body = reconstruct_client_frontmatter(client_fm, body)

        frontmatter[body_field] = body

        # Derive name from filename if missing
        derived_name = file_path.stem
        if "name" not in frontmatter or not frontmatter["name"]:
            frontmatter["name"] = derived_name

        # Derive ID from filename if missing
        id_field_map = {
            "Concept": "concept_id",
            "Project": "project_id",
            "Skill": "skill_id",
            "Reflection": "reflection_id",
            "Artifact": "artifact_id",
        }
        model_name = model_class.__name__
        if model_name in id_field_map:  # pragma: no branch
            id_field = id_field_map[model_name]
            if id_field not in frontmatter or not frontmatter[id_field]:
                frontmatter[id_field] = derived_name

        # For Concepts, derive parent_path from directory structure
        # Supports both flat (Name.md) and folder (Name/Name.md) formats
        if model_name == "Concept" and base_dir is not None:
            # Detect format: folder format if filename matches parent dir name
            is_folder_format = file_path.parent.name == file_path.stem

            if is_folder_format:
                # Folder format: Parent/Parent.md -> go up twice
                parent_dir = file_path.parent.parent
            else:
                # Flat format: Name.md -> go up once
                parent_dir = file_path.parent

            if parent_dir != base_dir:
                try:
                    rel_path = parent_dir.relative_to(base_dir)
                    parent_path = str(rel_path).replace("\\", "/")
                    if parent_path and parent_path != ".":
                        frontmatter["parent_path"] = parent_path
                except ValueError:
                    pass

        return model_class.model_validate(frontmatter)

    def _load_by_id(
        self, model_type: str, id_field: str, id_value: str, model_class: type[T]
    ) -> T | None:
        """Load an object by searching for its ID in all files.

        For Concepts, searches recursively through subdirectories.
        """
        dir_path = self._get_dir(model_type)
        if not dir_path.exists():
            return None
        body_fields = BODY_FIELDS.get(model_type, set())
        body_field = next(iter(body_fields), None)

        # Use recursive glob for Concepts, flat glob for others
        glob_pattern = "**/*.md" if model_type == "Concept" else "*.md"

        for file_path in dir_path.glob(glob_pattern):
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(content)

            derived_name = file_path.stem

            # Get ID from frontmatter, or derive from filename if missing
            file_id = frontmatter.get(id_field)
            if not file_id:
                file_id = derived_name

            if file_id == id_value:
                # Reconstruct client frontmatter in body if present
                client_fm = frontmatter.pop("client", None)
                if client_fm and isinstance(client_fm, dict):
                    body = reconstruct_client_frontmatter(client_fm, body)

                if body_field:  # pragma: no branch
                    frontmatter[body_field] = body
                # Ensure ID field is set for model validation
                if id_field not in frontmatter or not frontmatter[id_field]:
                    frontmatter[id_field] = derived_name
                # Also derive name if missing
                if "name" not in frontmatter or not frontmatter["name"]:
                    frontmatter["name"] = derived_name
                # For Concepts, derive parent_path from directory structure
                # Supports both flat (Name.md) and folder (Name/Name.md) formats
                if model_type == "Concept":
                    # Detect format: folder format if filename matches parent dir
                    is_folder_format = file_path.parent.name == file_path.stem

                    if is_folder_format:
                        # Folder format: Parent/Parent.md -> go up twice
                        parent_dir = file_path.parent.parent
                    else:
                        # Flat format: Name.md -> go up once
                        parent_dir = file_path.parent

                    if parent_dir != dir_path:
                        try:
                            rel_path = parent_dir.relative_to(dir_path)
                            parent_path = str(rel_path).replace("\\", "/")
                            if parent_path and parent_path != ".":
                                frontmatter["parent_path"] = parent_path
                        except ValueError:
                            pass
                return model_class.model_validate(frontmatter)
        return None

    def _list_markdown_files(
        self,
        model_type: str,
        model_class: type[T],
        body_field: str,
        project_id: str | None,
    ) -> list[T]:
        """List all markdown files of a type.

        For Concepts, searches recursively through subdirectories.
        """
        dir_path = self._get_dir(model_type)
        if not dir_path.exists():
            return []

        # Use recursive glob for Concepts, flat glob for others
        glob_pattern = "**/*.md" if model_type == "Concept" else "*.md"
        base_dir = dir_path if model_type == "Concept" else None

        items = []
        for file_path in dir_path.glob(glob_pattern):
            obj = self._load_markdown_file(file_path, model_class, body_field, base_dir)
            if obj:  # pragma: no branch
                if project_id and hasattr(obj, "project_id"):
                    if obj.project_id != project_id:
                        continue
                items.append(obj)
        return items

    def _find_file_by_id(
        self, model_type: str, id_field: str, id_value: str
    ) -> Path | None:
        """Find the file path for an object by its ID.

        Returns the path to the file, or None if not found.
        Used when updating objects to detect if the file needs to be moved.
        """
        dir_path = self._get_dir(model_type)
        if not dir_path.exists():
            return None

        # Use recursive glob for Concepts, flat glob for others
        glob_pattern = "**/*.md" if model_type == "Concept" else "*.md"

        for file_path in dir_path.glob(glob_pattern):
            content = file_path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)
            if frontmatter.get(id_field) == id_value:
                return file_path
        return None

    def _delete_file(self, file_path: Path) -> bool:
        """Delete a file at the given path.

        Returns True if the file was deleted, False if it didn't exist.
        """
        if not file_path.exists():
            return False

        file_path.unlink()
        return True
