"""Data models for MCP Memory system.

All models use YAML frontmatter for metadata and markdown body for content.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


def generate_id(prefix: str) -> str:
    """Generate a unique ID with the given prefix.

    Uses ULID (Universally Unique Lexicographically Sortable Identifier)
    for time-sortable, unique IDs.
    """
    from ulid import ULID

    return f"{prefix}_{ULID()}"


class Message(BaseModel):
    """A single message in a thread."""

    role: Literal["user", "assistant", "system"]
    text: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Thread(BaseModel):
    """A conversation thread containing messages.

    Stored as YAML file (no markdown body needed).
    """

    thread_id: str = Field(default_factory=lambda: generate_id("t"))
    title: str | None = None  # Human-friendly title for the thread
    project_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    messages: list[Message] = Field(default_factory=list)
    summary: str | None = None  # For compacted threads


class Concept(BaseModel):
    """A concept or entity with associated knowledge.

    Stored as markdown with YAML frontmatter.
    Compatible with existing Obsidian files - derives name from filename if needed.
    """

    model_config = {"extra": "allow"}  # Allow Obsidian-specific fields

    concept_id: str = Field(default_factory=lambda: generate_id("c"))
    name: str = ""  # Can be derived from filename
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    project_id: str | None = None  # Optional project association
    tags: list[str] = Field(default_factory=list)
    text: str = ""  # Markdown body
    # Common Obsidian fields we preserve
    aliases: list[str] = Field(default_factory=list)


class Project(BaseModel):
    """A project that groups related threads, concepts, and reflections.

    Stored as markdown with YAML frontmatter.
    """

    project_id: str = Field(default_factory=lambda: generate_id("p"))
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    instructions: str = ""  # Markdown body with project-specific instructions


class Skill(BaseModel):
    """A reusable skill or procedure.

    Stored as markdown with YAML frontmatter.
    """

    skill_id: str = Field(default_factory=lambda: generate_id("s"))
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    instructions: str = ""  # Markdown body with step-by-step instructions


class Reflection(BaseModel):
    """An agent reflection or learning.

    Stored as markdown with YAML frontmatter.
    """

    reflection_id: str = Field(default_factory=lambda: generate_id("r"))
    project_id: str | None = None
    thread_id: str | None = None
    skill_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    text: str = ""  # Markdown body with the reflection content


class Artifact(BaseModel):
    """A collaborative document that the LLM and user work on together.

    Artifacts are persistent documents that can be linked to projects and
    accessed across different conversation threads. They represent work
    products like specifications, designs, code, or any document that
    evolves through collaboration.

    For code artifacts linked to Skills, the `path` field specifies the
    relative path within the artifacts directory (e.g., "my-skill/helper.py").
    Use `skill_id` to link the artifact back to its parent Skill.

    Stored as markdown with YAML frontmatter.
    """

    artifact_id: str = Field(default_factory=lambda: generate_id("a"))
    name: str  # Human-readable title for the artifact
    description: str = ""  # Brief description of the artifact's purpose
    content_type: str = "markdown"  # Type: markdown, code, json, yaml, etc.
    path: str | None = None  # Relative path for file-based artifacts
    skill_id: str | None = None  # Optional link to parent Skill
    project_id: str | None = None  # Optional project association
    originating_thread_id: str | None = None  # Thread where artifact was created
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    content: str = ""  # Markdown body with the artifact content


class MemoryConfig(BaseModel):
    """Configuration for the memory system.

    Directory names can be customized to match your existing structure.
    Set a directory to empty string to disable that feature.
    """

    base_path: str = "."
    # Directory names (customize to match your Obsidian vault)
    threads_dir: str = "Threads"
    concepts_dir: str = "Concepts"  # Could be "People", "Characters", "Notes", etc.
    projects_dir: str = "Projects"
    skills_dir: str = "Skills"  # Could be "Procedures", "How-To", etc.
    reflections_dir: str = "Reflections"
    artifacts_dir: str = "Artifacts"  # Collaborative documents
    # Search settings
    embedding_model: str = "all-MiniLM-L6-v2"  # Sentence transformer model
    index_path: str = ".memory_index"  # Where to store FAISS index
    # Additional directories to index (for flexible vault structures)
    extra_concept_dirs: list[str] = []  # e.g., ["People", "Characters", "Entities"]
