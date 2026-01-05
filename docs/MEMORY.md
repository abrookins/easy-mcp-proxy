# MCP Memory System

The repository includes an **experimental** MCP Memory server that provides portable, persistent memory for AI assistants. This is completely optional—the proxy works fine without it.

## Why File-Based Storage?

All memory data is stored as human-readable markdown files with YAML frontmatter. This design enables:

- **Sync across systems** via Obsidian, Dropbox, iCloud, or Git
- **Manual editing** in any text editor
- **Version control** for tracking changes over time
- **Portability** across any MCP-compatible AI tool

The memory server is designed to work with existing note systems. If you use Obsidian, you can point the memory server at your vault and it will read existing notes as concepts.

## Cross-Agent Compatibility

The memory system works across multiple AI assistants:

| Agent | Support Level |
|-------|---------------|
| **Augment** | Full support via MCP proxy |
| **Claude Code** | Full support via MCP proxy |
| **Claude Desktop** | Full support via MCP config |
| **ChatGPT** | Limited—MCP servers work in developer mode but not in project chats; the feature is unreliable |

Because all data is stored as local files, you maintain complete ownership and can access your memories from any tool that supports MCP.

## Memory Types

The system provides six entity types, each stored in its own directory:

### Threads (`Threads/*.yaml`)
Conversation continuity across sessions. Store both user and assistant messages to resume conversations later. The LLM should call `add_messages()` frequently during conversations—not just at the end.

### Concepts (`Concepts/*.md`)
Knowledge about users, topics, and entities. Use for:
- User preferences and communication style
- Facts about people, projects, or domains
- Background information worth remembering

### Skills (`Skills/*.md`)
Reusable procedures and workflows stored as markdown instructions. Good for:
- Recurring procedures the user follows
- Project-specific workflows
- Step-by-step instructions for complex tasks

### Artifacts (`Artifacts/*.md`)
Collaborative documents that evolve through conversation—specs, designs, code, research notes. Unlike concepts (knowledge), artifacts are work products. Key features:
- Link to projects via `project_id`
- Track originating conversation via `originating_thread_id`
- Materialize to disk with `write_artifact_to_disk()`

### Reflections (`Reflections/*.md`)
Learnings from errors or corrective feedback. When something goes wrong, the LLM records what happened and what to do differently. Before similar tasks, check `read_reflections()` to avoid repeating mistakes.

### Projects (`Projects/*.md`)
Group related threads, concepts, skills, and artifacts. Mirror project configuration from your IDE or workspace into persistent memory.

## Design: Skills + Artifacts for Large Code

A key design intention is keeping Skills readable while supporting large code files.

**For small code snippets** (under ~100 lines), embed them directly in the Skill's `instructions` field.

**For larger code files**, store them as separate Artifacts linked to the Skill:

1. Create an Artifact with `path` (e.g., `"my-skill/helper.py"`) and `skill_id` set
2. Reference the Artifact in the Skill's instructions
3. Use `write_artifact_to_disk()` to materialize code when needed
4. Use `sync_artifact_from_disk()` to update the Artifact after editing

Example Skill instructions with Artifacts:
```markdown
## Database Migration Helper

### Code Artifacts
- `db-migration/migrate.py` (artifact_id: a_xyz123) - Main migration script
- `db-migration/config.yaml` (artifact_id: a_abc456) - Configuration

### Steps
1. Write artifacts to disk: `write_artifact_to_disk("a_xyz123", "./scripts/")`
2. Run: `python scripts/db-migration/migrate.py`
3. After edits, sync back: `sync_artifact_from_disk("a_xyz123", "./scripts/db-migration/migrate.py")`
```

## MCP Client Limitations

### Server Instructions Problem

The MCP protocol supports sending "server instructions" during initialization—detailed guidance on how the LLM should use the tools. The memory server includes comprehensive instructions covering:

- When to create/update each entity type
- Workflow patterns (starting conversations, resuming work, syncing projects)
- Search strategy guidance
- Tool selection guidance

**However, most MCP clients ignore these instructions.** They don't incorporate them into the system prompt, making them useless for guiding LLM behavior.

### Workaround: `get_server_instructions` Tool

To help with this problem, we've added a `get_server_instructions` tool that the LLM can call to retrieve the same instructions. This works around the client limitation, but requires the LLM to know to call it.

You may want to add guidance to your system prompt or project instructions telling the LLM to call `get_server_instructions` at the start of sessions.

## Getting Started

### Initialize a memory directory

```bash
mcp-memory init --path /path/to/vault
```

This creates the directory structure:
```
/path/to/vault/
├── Threads/
├── Concepts/
├── Projects/
├── Skills/
├── Reflections/
├── Artifacts/
└── .mcp-memory.yaml
```

### Start the memory server

```bash
mcp-memory serve --path /path/to/vault
```

### Configure with the proxy

Add to your `config.yaml`:

```yaml
mcp_servers:
  memory:
    command: mcp-memory
    args:
      - serve
      - --path
      - /path/to/vault
```

### Custom directory names

If you have an existing Obsidian vault with different folder names, configure them in `.mcp-memory.yaml`:

```yaml
concepts_dir: "People"       # Instead of "Concepts"
skills_dir: "Procedures"     # Instead of "Skills"
extra_concept_dirs:          # Additional directories to index
  - "Characters"
  - "Entities"
```

## Search

The memory system includes local semantic search using sentence-transformers and FAISS. No cloud dependencies.

- Search indexes are stored in `.memory_index/`
- Automatic stale detection via file modification times
- Lazy model loading (only when search is first called)
- Rebuild manually with `mcp-memory build-index --path /path/to/vault`

