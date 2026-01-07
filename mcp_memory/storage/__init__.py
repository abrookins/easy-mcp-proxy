"""Storage package for MCP Memory.

This package provides file-based storage for memory objects, using
markdown files with YAML frontmatter.
"""

from mcp_memory.storage.artifact import ArtifactStorageMixin
from mcp_memory.storage.base import (
    BODY_FIELDS,
    BaseStorage,
    extract_client_frontmatter,
    format_frontmatter,
    parse_frontmatter,
    reconstruct_client_frontmatter,
)
from mcp_memory.storage.concept import ConceptStorageMixin
from mcp_memory.storage.episode import EpisodeStorageMixin
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
    EpisodeStorageMixin,
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
    "extract_client_frontmatter",
    "reconstruct_client_frontmatter",
    "BODY_FIELDS",
    "BaseStorage",
    "ThreadStorageMixin",
    "ConceptStorageMixin",
    "ProjectStorageMixin",
    "SkillStorageMixin",
    "ReflectionStorageMixin",
    "ArtifactStorageMixin",
    "EpisodeStorageMixin",
]
