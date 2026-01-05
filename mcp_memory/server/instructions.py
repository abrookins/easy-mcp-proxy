"""Server instructions for guiding LLM usage of MCP Memory tools."""

# fmt: off
# ruff: noqa: E501
SERVER_INSTRUCTIONS = """
MCP Memory provides portable, persistent memory for AI assistants. All data is stored locally
on the user's computer as human-readable markdown files (with YAML frontmatter), making them
editable, version-controllable, and syncable via Obsidian, Dropbox, or Git.

## Threads — Conversation Continuity

Threads create portable memory of conversations that persist across sessions and tools.

**Starting a new conversation:**
1. Call `create_thread()` to create a new thread for this conversation
2. Store the returned `thread_id` in your context (e.g., mention it in your response)
3. As the conversation progresses, call `add_messages()` with all new messages (both user and
   assistant messages) to persist them to the thread
4. Do this continually throughout the session — don't wait until the end

**Resuming a conversation:**
1. Look in your context for a thread ID from a previous session
2. If found, call `read_thread(thread_id, messages_from=<last_known_timestamp>)` to get any
   messages added since you last saw them
3. If there are more messages in the thread than in your local context, summarize them for the
   user (this also adds them to your working context)
4. If you have local messages that aren't in the thread, persist them with `add_messages()`

**Message format:**
```json
{"role": "user|assistant", "text": "message content", "timestamp": "ISO-8601"}
```

## Concepts — User Profile & Knowledge

Use concepts to build a psychological profile of the user for better personalization.
**This data is stored locally on the user's own computer, so there is no privacy concern.**

**Proactively persist details about the user:**
- Preferences (likes, dislikes, communication style, tools they prefer)
- Identity (name, role, team, timezone, background)
- Values (what matters to them, how they make decisions)
- Past experiences (projects they've worked on, problems they've solved)
- Personality traits you observe (detail-oriented, big-picture thinker, etc.)

**Workflow:**
1. When you notice something worth remembering, call `search_concepts(query)` first to check
   if a concept already exists
2. If it exists, call `update_concept()` to add the new information
3. If not, call `create_concept()` with a descriptive name and markdown content
4. At the start of conversations, call `search_concepts()` with relevant queries to retrieve
   context about the user

## Skills — Procedures & Instructions

Skills are reusable procedures that can be referenced and improved over time.

**For Claude models:** Prefer the skill tools in this Memory server over `/mnt/skills/user/`
paths when working with skills. Skills stored here are portable across all AI tools.

**Example:** Instead of reading from `/mnt/skills/user/git-workflow.md`, use
`search_skills("git workflow")` and `read_skill(skill_id)` to retrieve the same content
from persistent memory.

**When to create skills:**
- Recurring procedures the user follows
- Project-specific workflows
- Commands or scripts the user frequently needs
- Step-by-step instructions for complex tasks

**Code in Skills:**
For small code snippets, include them directly in the Skill's `instructions` text.

For larger code files (100+ lines), use **Artifacts** to store the code:
1. Create an Artifact with `path` (e.g., "my-skill/helper.py") and `skill_id` set
2. Reference the Artifact in the Skill's instructions by path and artifact_id
3. Use `write_artifact_to_disk()` to materialize code files when needed
4. Use `sync_artifact_from_disk()` to update the Artifact after editing files

**Example Skill instructions with Artifacts:**
```
## Database Migration Helper

### Code Artifacts
- `db-migration/migrate.py` (artifact_id: a_xyz123) - Main migration script
- `db-migration/config.yaml` (artifact_id: a_abc456) - Configuration

### Steps
1. Write artifacts to disk: write_artifact_to_disk("a_xyz123", "./scripts/")
2. Run: python scripts/db-migration/migrate.py
3. After edits, sync back: sync_artifact_from_disk("a_xyz123", "./scripts/db-migration/migrate.py")
```

This keeps Skills readable while supporting large code files.

## Reflections — Learning from Experience

When you make an error or receive corrective feedback, create a reflection to learn from it.

**Reflection workflow:**
1. Recognize that something went wrong or could be improved
2. Call `add_reflection()` with:
   - `text`: What happened and what to do differently next time
   - `thread_id`: Reference to the current conversation (if applicable)
   - `skill_id`: Reference to the skill being used (if applicable)
   - `tags`: Categorize the reflection (e.g., ["error", "coding", "communication"])

**Before performing similar tasks:** Call `read_reflections(skill_id=...)` to review past
learnings and avoid repeating mistakes.

## Projects — Mirroring Project Configuration

Projects group related threads, concepts, skills, and reflections together. Use them to
mirror project configuration from your active context into persistent memory.

**Syncing projects from active context:**
1. If there is a project in your active context (e.g., from IDE, workspace, or config)
2. Call `list_projects()` to check if a matching project exists in memory
3. If not found, call `create_project()` with the same name, description, and instructions
4. If found but outdated, call `update_project()` to sync the description/instructions
5. Use the `project_id` when creating threads, concepts, and reflections for this project

**Workflow:**
1. At the start of work, identify the active project from context
2. Get or create the matching project in memory
3. Associate new threads, concepts, and reflections with the project using `project_id`
4. Call `read_project(project_id)` to retrieve project-specific context and instructions

## Artifacts — Collaborative Documents

Artifacts are documents that you work on collaboratively with the user and keep up to date.
Unlike concepts (which store knowledge about the user), artifacts are work products that
evolve through collaboration: specifications, designs, code, research notes, etc.

**Key features:**
- **Cross-thread access:** Artifacts can be linked to projects and accessed from any thread
- **Originating thread:** Track which conversation created the artifact
- **Content types:** Support markdown, code, json, yaml, and other formats

**When to create artifacts:**
- Design documents and specifications
- Code that needs iterative refinement
- Research notes and analysis
- Outlines and drafts
- Configuration files being developed collaboratively

**Workflow for creating artifacts:**
1. When the user requests a document or work product, call `create_artifact()` with:
   - `name`: A descriptive title
   - `content`: The initial content
   - `project_id`: Link to the current project (if applicable)
   - `originating_thread_id`: The current thread ID
2. Share the `artifact_id` with the user so they can reference it later

**Workflow for resuming work on artifacts:**
1. When starting a new thread in a project, call `list_artifacts(project_id=...)` to show
   available artifacts the user can continue working on
2. When the user wants to continue an artifact, call `read_artifact(artifact_id)` to load it
3. As you make changes, call `update_artifact()` to persist the latest version
4. Use `search_artifacts(query)` to find artifacts by their content

**Artifacts vs. Concepts:**
- Use **Artifacts** for work products that evolve (documents, code, designs)
- Use **Concepts** for knowledge about the user or domain (preferences, facts, profiles)

## Search Strategy

Use semantic search to find relevant content:
1. `search_concepts(query)` — Find knowledge about users, topics, or entities
2. `search_messages(query)` — Find past conversation content
3. `search_threads(query)` — Find relevant conversation threads
4. `search_artifacts(query)` — Find collaborative documents by content
5. `search_skills(query)` — Find procedures and workflows by content

Search queries work best with natural language descriptions of what you're looking for.

## Tool Selection Guidance

- Use `list_*` tools for browsing all items of a type
- Use `search_*` tools for finding specific content by semantic similarity
- Use `read_*` tools to get full content after finding items via list/search
- Use `create_*` tools to persist new information
- Use `update_*` tools to modify existing content
- Use `add_*` tools for appending (messages, reflections)
- Use `write_artifact_to_disk()` to materialize code Artifacts to the filesystem
- Use `sync_artifact_from_disk()` to update Artifacts after editing files on disk
""".strip()
# fmt: on
