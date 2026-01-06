# ADR-006: Hierarchical Memory and Modular Architecture

## Status

Accepted

## Context

After implementing the authentication system (ADR-005), significant refactoring of the memory system was undertaken on January 5-6, 2026. The original flat concept storage proved limiting for organizing knowledge hierarchically (e.g., user profiles with nested preferences, characters with attributes). Additionally, the monolithic `server.py` (~950 lines) and `storage.py` (~390 lines) became difficult to maintain.

## Key Decisions

### 1. Hierarchical Concept Storage

**Problem**: Flat concept storage made it difficult to organize related knowledge (e.g., a person's preferences, projects, and notes under their profile).

**Solution**: Concepts now support a folder-based hierarchy using `parent_path`:

```
Concepts/
  Andrew Brookins/
    Andrew Brookins.md    # Root concept about Andrew
    Preferences/
      Preferences.md      # parent_path="Andrew Brookins"
    Projects/
      Projects.md
  Lane Harker/
    Lane Harker.md
    Characters/
      Characters.md
      Lane/
        Lane.md           # parent_path="Lane Harker/Characters"
```

**Key design choices**:
- Every concept stored as `Name/Name.md` (folder contains same-named file)
- `parent_path` field determines folder location
- `full_path` property computes complete path (e.g., "Lane Harker/Characters/Lane")
- Recursive glob patterns for searching subdirectories
- Empty parent directories cleaned up on deletion

### 2. New Concept Model Fields

**Additions to `Concept` model**:

```python
class Concept(BaseModel):
    parent_path: str | None = None  # Hierarchical path to parent folder
    links: list[str] = Field(default_factory=list)  # Cross-references

    @property
    def full_path(self) -> str:
        """Returns 'parent_path/name' or just 'name' if no parent."""
```

### 3. New Hierarchical Navigation Tools

**Added tools for tree navigation**:

| Tool | Purpose |
|------|---------|
| `read_concept_by_path(path)` | Load concept by "Parent/Child" path |
| `list_concept_children(parent_path)` | List direct children of a path |
| `list_concept_child_paths(parent_path)` | Efficient path-only listing (no file I/O) |

**Output enhancement**: `read_concept()` and `read_concept_by_path()` now include child paths in output for single-call hierarchy discovery.

### 4. Modular Server Architecture

**Problem**: Monolithic `server.py` was ~950 lines and growing.

**Solution**: Split into focused modules under `mcp_memory/server/`:

```
mcp_memory/server/
├── __init__.py           # Public exports
├── core.py               # create_memory_server() factory
├── instructions.py       # SERVER_INSTRUCTIONS constant
├── utils.py              # Shared helpers (_text, _format_concept)
├── thread_tools.py       # Thread CRUD and search
├── concept_tools.py      # Concept CRUD with hierarchy
├── project_tools.py      # Project management
├── skill_tools.py        # Skill procedures
├── reflection_tools.py   # Learning reflections
└── artifact_tools.py     # Collaborative documents
```

**Pattern**: Each `*_tools.py` exports a `register_*_tools(mcp, storage, searcher)` function.

### 5. Modular Storage Architecture

**Problem**: Monolithic `storage.py` was ~390 lines with mixed concerns.

**Solution**: Split into base class with mixins under `mcp_memory/storage/`:

```
mcp_memory/storage/
├── __init__.py      # MemoryStorage class (combines all mixins)
├── base.py          # BaseStorage with file I/O primitives
├── thread.py        # ThreadStorageMixin
├── concept.py       # ConceptStorageMixin (hierarchy logic)
├── project.py       # ProjectStorageMixin
├── skill.py         # SkillStorageMixin
├── reflection.py    # ReflectionStorageMixin
└── artifact.py      # ArtifactStorageMixin
```

**Composition**: `MemoryStorage` inherits from `BaseStorage` and all mixins.

### 6. Client Frontmatter Round-Tripping

**Problem**: Clients (like Obsidian plugins) may submit content with their own YAML frontmatter, which was being lost.

**Solution**: Detect and preserve client frontmatter:

```python
# On save: detect frontmatter in text content
client_fm, remaining = extract_client_frontmatter(text)
if client_fm:
    frontmatter["client"] = client_fm  # Store under 'client' key
    body = remaining

# On load: reconstruct original format
if "client" in frontmatter:
    body = reconstruct_client_frontmatter(frontmatter["client"], body)
```

### 7. Search Index Updates

**Changes to `MemorySearcher`**:
- Recursive glob for concept files: `**/*.md` instead of `*.md`
- Full path included in searchable text for better discovery
- Search results include `path` field alongside `name`

## Consequences

- Concepts can now be organized in intuitive hierarchies
- Obsidian vault structures are fully supported
- Codebase is more maintainable with focused modules
- Each entity type can evolve independently
- Client applications can round-trip their own frontmatter
- Navigation is efficient with path-based lookups
- Comprehensive test coverage maintained (100% requirement)

## Migration Notes

- Existing flat concepts continue to work (no parent_path = root level)
- No database migration needed (file-based storage)
- New folder structure created automatically on save

