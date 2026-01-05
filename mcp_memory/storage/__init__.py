"""Storage package for MCP Memory.

This package provides file-based storage for memory objects, using
markdown files with YAML frontmatter.
"""

from mcp_memory.storage.artifact import ArtifactStorageMixin
from mcp_memory.storage.base import (
    BODY_FIELDS,
    BaseStorage,
    format_frontmatter,
    parse_frontmatter,
)
from mcp_memory.storage.concept import ConceptStorageMixin
from mcp_memory.storage.project import ProjectStorageMixin
from mcp_memory.storage.reflection import ReflectionStorageMixin
from mcp_memory.storage.skill import SkillStorageMixin
from mcp_memory.storage.thread import ThreadStorageMixin


class MemoryStorage(
    ThreadStorageMixin,
    ConceptStorageMixin,
    ProjectStorageMixin,
    SkillStorageMixin,
    ReflectionStorageMixin,
    ArtifactStorageMixin,
    BaseStorage,
):
    """File-based storage for memory objects.

    Combines all storage mixins with the base storage class.
    """

    pass


__all__ = [
    "MemoryStorage",
    "parse_frontmatter",
    "format_frontmatter",
    "BODY_FIELDS",
    "BaseStorage",
    "ThreadStorageMixin",
    "ConceptStorageMixin",
    "ProjectStorageMixin",
    "SkillStorageMixin",
    "ReflectionStorageMixin",
    "ArtifactStorageMixin",
]

