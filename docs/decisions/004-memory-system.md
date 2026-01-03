# ADR-004: MCP Memory System

## Status

Accepted

## Context

After establishing the core proxy functionality (ADR-003), a need arose for a portable, persistent memory system that AI assistants can use across different tools and sessions. The memory system was implemented on January 2-3, 2026.

## Key Decisions

### 1. MCP Memory as a Separate Package

**Problem**: AI assistants lack persistent memory across sessions and tools. Existing solutions are either cloud-dependent or tied to specific platforms.

**Solution**: Created `mcp_memory` as a standalone MCP server within the same repository:

```
mcp_memory/
├── __init__.py     # Public exports
├── cli.py          # CLI commands (serve, init, build-index)
├── models.py       # Pydantic data models
├── server.py       # MCP server with tools
├── storage.py      # File-based storage layer
└── search.py       # Vector search with FAISS
```

**Rationale**: Keeping memory separate from the proxy allows independent deployment while sharing infrastructure. The memory system can be used standalone or composed with other MCP servers via the proxy.

### 2. File-Based Storage with YAML Frontmatter

**Problem**: Memory data should be human-readable, editable, version-controllable, and syncable via standard tools (Git, Dropbox, Obsidian).

**Solution**: All data stored as markdown files with YAML frontmatter:

```markdown
---
concept_id: c_01JGPX...
name: Andrew
tags: [user, preferences]
created_at: 2026-01-02T10:30:00
---

Andrew prefers concise responses and dark mode interfaces.
Timezone: PST. Primary language: Python.
```

**Key design choices**:
- Threads stored as pure YAML (messages as list)
- Concepts, Projects, Skills, Reflections, Artifacts use markdown body for content
- Obsidian compatibility: derives `name` from filename if not in frontmatter
- Supports Obsidian `aliases` field for alternative names

### 3. Entity Model Design

**Six entity types** with distinct purposes:

| Entity | Purpose | Storage |
|--------|---------|---------|
| **Thread** | Conversation continuity | `Threads/*.yaml` |
| **Concept** | User profile & knowledge | `Concepts/*.md` |
| **Project** | Group related items | `Projects/*.md` |
| **Skill** | Reusable procedures | `Skills/*.md` |
| **Reflection** | Learning from errors | `Reflections/*.md` |
| **Artifact** | Collaborative documents | `Artifacts/*.md` |

**Artifacts vs Concepts**: Artifacts are work products that evolve (specs, code); Concepts store knowledge about users/domains.

### 4. Vector Search with FAISS

**Problem**: Need semantic search across all memory content without cloud dependencies.

**Solution**: Local vector search using sentence-transformers and FAISS:

```python
config = MemoryConfig(
    embedding_model="all-MiniLM-L6-v2",  # 384-dim embeddings
    index_path=".memory_index"
)
```

**Implementation details**:
- Automatic stale detection via file modification times
- Lazy model loading (only when search is first called)
- Incremental index updates for new content
- Index persisted to disk (`index.faiss`, `id_map.json`, `mtimes.json`)

### 5. Server Instructions for LLM Guidance

**Problem**: LLMs need guidance on how to use memory tools effectively.

**Solution**: Comprehensive `SERVER_INSTRUCTIONS` in `server.py` providing:
- When to create/update each entity type
- Workflow patterns (starting conversations, resuming work, syncing projects)
- Search strategy guidance
- Tool selection guidance

### 6. CLI Entry Point

**Addition**: `mcp-memory` command registered in `pyproject.toml`:

```bash
mcp-memory serve --path /path/to/vault  # Start MCP server
mcp-memory init --path /path/to/vault   # Initialize directory structure
mcp-memory build-index --path .         # Rebuild search index
```

Supports auto-detection of `.mcp-memory.yaml` config file.

### 7. Configurable Directory Structure

**Problem**: Users may have existing vault structures (Obsidian) with different directory names.

**Solution**: All directory names configurable via `MemoryConfig`:

```yaml
# .mcp-memory.yaml
concepts_dir: "People"       # Instead of "Concepts"
skills_dir: "Procedures"     # Instead of "Skills"
extra_concept_dirs:          # Additional directories to index
  - "Characters"
  - "Entities"
```

## CI/CD Improvements

### Test Timeout Fix

**Problem**: `test_proxy_initialize_creates_all_clients` was hanging indefinitely on Linux CI because `echo` is not a valid MCP server.

**Solution**: 
- Mocked `refresh_upstream_tools` in the affected test
- Added `timeout-minutes: 15` to CI test job as safety net

## Dependencies Added

```toml
dependencies = [
    "sentence-transformers>=2.2.0",  # Text embeddings
    "faiss-cpu>=1.7.0",              # Vector search
    "numpy>=1.24.0",                 # Numerical operations
]
```

## Consequences

- Portable memory across any MCP-compatible AI tool
- Data ownership: all files local to user's filesystem
- Obsidian/Git/Dropbox compatibility for syncing
- No cloud dependencies for vector search
- Comprehensive test coverage maintained (100% requirement)
- Clear separation between proxy and memory concerns

