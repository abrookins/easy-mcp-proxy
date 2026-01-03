"""File storage layer for MCP Memory.

Handles reading/writing markdown files with YAML frontmatter.
"""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from mcp_memory.models import (
    Artifact,
    Concept,
    MemoryConfig,
    Project,
    Reflection,
    Skill,
    Thread,
)

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


def format_frontmatter(data: dict, body: str = "") -> str:
    """Format data as YAML frontmatter with optional markdown body."""
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    if body:
        return f"---\n{yaml_str}---\n\n{body}"
    return f"---\n{yaml_str}---\n"


class MemoryStorage:
    """File-based storage for memory objects."""

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

    def _get_filename(self, obj: BaseModel) -> str:
        """Get filename for an object."""
        model_type = type(obj).__name__
        if model_type == "Thread":
            return f"{obj.thread_id}.yaml"
        elif model_type == "Concept":
            # Use name for concepts (sanitized)
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Project":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Skill":
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        elif model_type == "Artifact":
            # Use name for artifacts (sanitized)
            safe_name = self._sanitize_name(obj.name)
            return f"{safe_name}.md"
        else:  # Reflection
            return f"{obj.reflection_id}.md"

    def save(self, obj: BaseModel) -> Path:
        """Save an object to disk."""
        model_type = type(obj).__name__
        dir_path = self._ensure_dir(model_type)
        filename = self._get_filename(obj)
        file_path = dir_path / filename

        # Convert to dict
        data = obj.model_dump(mode="json")

        # Separate body fields from frontmatter
        body_field_names = BODY_FIELDS.get(model_type, set())
        body_parts = []
        frontmatter = {}

        for key, value in data.items():
            if key in body_field_names:
                if value:
                    body_parts.append(str(value))
            else:
                frontmatter[key] = value

        body = "\n\n".join(body_parts)

        # Write file
        if model_type == "Thread":
            # Threads are pure YAML
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        else:
            content = format_frontmatter(frontmatter, body)

        file_path.write_text(content, encoding="utf-8")
        return file_path

    def load_thread(self, thread_id: str) -> Thread | None:
        """Load a thread by ID."""
        dir_path = self._get_dir("Thread")
        file_path = dir_path / f"{thread_id}.yaml"
        if not file_path.exists():
            return None
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return Thread.model_validate(data)

    def load_concept(self, concept_id: str) -> Concept | None:
        """Load a concept by ID (searches all concept files)."""
        return self._load_by_id("Concept", "concept_id", concept_id, Concept)

    def load_concept_by_name(self, name: str) -> Concept | None:
        """Load a concept by name.

        Tries exact filename first (for Obsidian), then sanitized name.
        Also searches frontmatter 'name' field as fallback.
        """
        dir_path = self._get_dir("Concept")
        if not dir_path.exists():
            return None

        # Try exact filename first
        file_path = dir_path / f"{name}.md"
        if file_path.exists():
            return self._load_markdown_file(file_path, Concept, "text")

        # Try sanitized filename
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        file_path = dir_path / f"{safe_name}.md"
        if file_path.exists():
            return self._load_markdown_file(file_path, Concept, "text")

        # Search all files for matching name in frontmatter or filename
        name_lower = name.lower()
        for file_path in dir_path.glob("*.md"):
            if file_path.stem.lower() == name_lower:  # pragma: no cover
                return self._load_markdown_file(file_path, Concept, "text")
            # Also check frontmatter name field
            content = file_path.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)
            if frontmatter.get("name", "").lower() == name_lower:
                return self._load_markdown_file(file_path, Concept, "text")
            # Check aliases (Obsidian feature)
            aliases = frontmatter.get("aliases", [])
            if isinstance(aliases, list) and any(  # pragma: no branch
                a.lower() == name_lower for a in aliases
            ):
                return self._load_markdown_file(file_path, Concept, "text")

        return None

    def load_project(self, project_id: str) -> Project | None:
        """Load a project by ID."""
        return self._load_by_id("Project", "project_id", project_id, Project)

    def load_project_by_name(self, name: str) -> Project | None:
        """Load a project by name."""
        dir_path = self._get_dir("Project")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        file_path = dir_path / f"{safe_name}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Project, "instructions")

    def load_skill(self, skill_id: str) -> Skill | None:
        """Load a skill by ID."""
        return self._load_by_id("Skill", "skill_id", skill_id, Skill)

    def load_reflection(self, reflection_id: str) -> Reflection | None:
        """Load a reflection by ID."""
        dir_path = self._get_dir("Reflection")
        file_path = dir_path / f"{reflection_id}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Reflection, "text")

    def _load_markdown_file(
        self, file_path: Path, model_class: type[T], body_field: str
    ) -> T | None:
        """Load a markdown file with frontmatter into a model.

        For Obsidian compatibility:
        - Derives 'name' from filename if not in frontmatter
        - Derives ID from filename if not in frontmatter
        - Allows extra frontmatter fields
        """
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(content)
        frontmatter[body_field] = body

        # Derive name from filename if missing (for Obsidian files)
        filename_stem = file_path.stem  # e.g., "Lane Harker" from "Lane Harker.md"
        if "name" not in frontmatter or not frontmatter["name"]:
            frontmatter["name"] = filename_stem

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
                # Use filename as ID for consistency
                frontmatter[id_field] = filename_stem

        return model_class.model_validate(frontmatter)

    def _load_by_id(
        self, model_type: str, id_field: str, id_value: str, model_class: type[T]
    ) -> T | None:
        """Load an object by searching for its ID in all files."""
        dir_path = self._get_dir(model_type)
        if not dir_path.exists():
            return None
        body_fields = BODY_FIELDS.get(model_type, set())
        body_field = next(iter(body_fields), None)

        for file_path in dir_path.glob("*.md"):
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(content)

            # Get ID from frontmatter, or derive from filename if missing
            # (consistent with _load_markdown_file behavior)
            file_id = frontmatter.get(id_field)
            if not file_id:
                file_id = file_path.stem

            if file_id == id_value:
                if body_field:  # pragma: no branch
                    frontmatter[body_field] = body
                # Ensure ID field is set for model validation
                if id_field not in frontmatter or not frontmatter[id_field]:
                    frontmatter[id_field] = file_path.stem
                # Also derive name from filename if missing
                if "name" not in frontmatter or not frontmatter["name"]:
                    frontmatter["name"] = file_path.stem
                return model_class.model_validate(frontmatter)
        return None

    def list_threads(self, project_id: str | None = None) -> list[Thread]:
        """List all threads, optionally filtered by project."""
        dir_path = self._get_dir("Thread")
        if not dir_path.exists():
            return []
        threads = []
        for file_path in dir_path.glob("*.yaml"):
            content = file_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            thread = Thread.model_validate(data)
            if project_id is None or thread.project_id == project_id:
                threads.append(thread)
        return threads

    def list_concepts(self, project_id: str | None = None) -> list[Concept]:
        """List all concepts, optionally filtered by project.

        Also searches extra_concept_dirs if configured.
        """
        concepts = self._list_markdown_files("Concept", Concept, "text", project_id)

        # Also search extra concept directories
        for extra_dir in self.config.extra_concept_dirs:
            extra_path = self.base_path / extra_dir
            if extra_path.exists():  # pragma: no branch
                for file_path in extra_path.glob("*.md"):
                    try:
                        obj = self._load_markdown_file(file_path, Concept, "text")
                        if obj:  # pragma: no branch
                            if project_id and hasattr(obj, "project_id"):
                                if obj.project_id != project_id:
                                    continue
                            concepts.append(obj)
                    except Exception:
                        # Skip files that can't be parsed
                        pass

        return concepts

    def list_projects(self) -> list[Project]:
        """List all projects."""
        return self._list_markdown_files("Project", Project, "instructions", None)

    def list_skills(self) -> list[Skill]:
        """List all skills."""
        return self._list_markdown_files("Skill", Skill, "instructions", None)

    def list_reflections(
        self, project_id: str | None = None, skill_id: str | None = None
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

    def load_artifact(self, artifact_id: str) -> Artifact | None:
        """Load an artifact by ID."""
        return self._load_by_id("Artifact", "artifact_id", artifact_id, Artifact)

    def load_artifact_by_name(self, name: str) -> Artifact | None:
        """Load an artifact by name."""
        dir_path = self._get_dir("Artifact")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
        file_path = dir_path / f"{safe_name}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Artifact, "content")

    def list_artifacts(self, project_id: str | None = None) -> list[Artifact]:
        """List all artifacts, optionally filtered by project."""
        return self._list_markdown_files("Artifact", Artifact, "content", project_id)

    def _list_markdown_files(
        self,
        model_type: str,
        model_class: type[T],
        body_field: str,
        project_id: str | None,
    ) -> list[T]:
        """List all markdown files of a type."""
        dir_path = self._get_dir(model_type)
        if not dir_path.exists():
            return []
        items = []
        for file_path in dir_path.glob("*.md"):
            obj = self._load_markdown_file(file_path, model_class, body_field)
            if obj:  # pragma: no branch
                if project_id and hasattr(obj, "project_id"):
                    if obj.project_id != project_id:
                        continue
                items.append(obj)
        return items
