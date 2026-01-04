"""MCP Server for the memory system.

Provides tools for managing threads, concepts, projects, skills, and reflections.
"""

from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import (
    Artifact,
    Concept,
    MemoryConfig,
    Message,
    Project,
    Reflection,
    Skill,
    Thread,
)
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

# Server instructions for guiding LLM usage
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


def create_memory_server(
    base_path: str = ".",
    name: str = "MCP Memory",
    config: MemoryConfig | None = None,
    embedding_model=None,
) -> FastMCP:
    """Create an MCP server with memory tools.

    Args:
        base_path: Base path for storage (ignored if config provided)
        name: Name for the MCP server
        config: Optional MemoryConfig (if not provided, uses base_path)
        embedding_model: Optional pre-loaded sentence transformer model (for testing)
    """
    if config is None:
        config = MemoryConfig(base_path=base_path)
    storage = MemoryStorage(config)
    searcher = MemorySearcher(storage, config, model=embedding_model)

    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS)

    # ============ Thread Tools ============

    @mcp.tool()
    def create_thread(
        project_id: str | None = None,
        thread_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Create a new conversation thread for persisting messages across sessions. Call this at the start of conversations you want to remember. Title is auto-derived from the first message if not provided."""
        thread = Thread(project_id=project_id, title=title)
        if thread_id:
            thread.thread_id = thread_id
        storage.save(thread)
        return {"thread_id": thread.thread_id, "title": thread.title, "created": True}

    def _text(text: str) -> TextContent:
        """Wrap text in TextContent for MCP response."""
        return TextContent(type="text", text=text)

    @mcp.tool()
    def read_thread(
        thread_id: str,
        messages_from: str | None = None,
    ) -> TextContent:
        """Retrieve a thread and its messages. Use when resuming a conversation to restore context. Pass messages_from as ISO timestamp to get only messages added since your last sync."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return _text(f"Thread {thread_id} not found")

        messages = thread.messages
        if messages_from:
            from_dt = datetime.fromisoformat(messages_from)
            messages = [m for m in messages if m.timestamp >= from_dt]

        lines = [
            f"# {thread.title or 'Untitled'}",
            f"**Thread ID:** `{thread.thread_id}`",
        ]
        if thread.project_id:
            lines.append(f"**Project:** `{thread.project_id}`")
        if thread.summary:
            lines.append(f"\n**Summary:** {thread.summary}")
        lines.append(f"\n## Messages ({len(messages)})\n")
        for m in messages:
            lines.append(f"**{m.role}** ({m.timestamp:%Y-%m-%d %H:%M}):\n{m.text}\n")
        return _text("\n".join(lines))

    def _derive_title_from_text(text: str, max_length: int = 60) -> str:
        """Derive a thread title from message text.

        Takes the first line or sentence, truncates to max_length at word boundary.
        """
        # Get first line
        first_line = text.split("\n")[0].strip()

        # If short enough, use as-is
        if len(first_line) <= max_length:
            return first_line

        # Truncate at word boundary
        truncated = first_line[:max_length].rsplit(" ", 1)[0]
        return truncated + "..." if truncated else first_line[:max_length] + "..."

    @mcp.tool()
    def add_messages(
        thread_id: str,
        messages: list[dict],
    ) -> dict:
        """Append messages to an existing thread. Call frequently during conversations to persist context—don't wait until the end. Each message needs 'role' (user/assistant) and 'text' fields; 'timestamp' is optional (defaults to now)."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        for msg_data in messages:
            ts_str = msg_data.get("timestamp", datetime.now().isoformat())
            msg = Message(
                role=msg_data["role"],
                text=msg_data["text"],
                timestamp=datetime.fromisoformat(ts_str),
            )
            thread.messages.append(msg)
            # Add to search index
            searcher.add_to_index(
                "message",
                msg.text,
                {
                    "thread_id": thread_id,
                    "message_index": len(thread.messages) - 1,
                    "project_id": thread.project_id,
                },
            )

        # Auto-derive title from first message if not already set
        if not thread.title and thread.messages:
            thread.title = _derive_title_from_text(thread.messages[0].text)

        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "message_count": len(thread.messages)}

    @mcp.tool()
    def search_messages(
        query: str,
        thread_id: str | None = None,
        project_id: str | None = None,
        limit: int = 10,
    ) -> TextContent:
        """Find past conversation content using semantic search. Returns thread IDs and message indices—use read_thread() to get full context. Filter by thread_id or project_id to narrow results."""
        results = searcher.search_messages(
            query, limit=limit, thread_id=thread_id, project_id=project_id
        )
        if not results:
            return _text(f"No messages found for query: {query}")
        lines = [f"# Message Search Results ({len(results)})\n"]
        for r in results:
            lines.append(
                f"- Thread `{r['thread_id']}` msg#{r['message_index']} "
                f"(score: {r['score']:.2f})"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def search_threads(query: str, limit: int = 10) -> TextContent:
        """Find conversation threads by their message content using semantic search. Use this to locate past conversations on a topic. Returns thread IDs—use read_thread() to get the full conversation."""
        results = searcher.search_threads(query, limit=limit)
        if not results:
            return _text(f"No threads found for query: {query}")
        lines = [f"# Thread Search Results ({len(results)})\n"]
        for r in results:
            title = r.get("title", "Untitled")
            lines.append(f"- `{r['thread_id']}` **{title}** (score: {r['score']:.2f})")
        return _text("\n".join(lines))

    @mcp.tool()
    def compact_thread(thread_id: str, summary: str) -> dict:
        """Replace a thread's messages with a summary to reduce storage. Use for long threads where individual messages are no longer needed. The summary becomes the thread's new context—messages are deleted permanently."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        thread.summary = summary
        thread.messages = []  # Clear messages after summarizing
        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "compacted": True}

    @mcp.tool()
    def list_threads(project_id: str | None = None, limit: int = 50) -> TextContent:
        """Browse all conversation threads, sorted by most recently updated. Use to find threads when you don't have a specific search query. Filter by project_id to see only threads for a specific project."""
        threads = storage.list_threads(project_id=project_id)
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        threads = threads[:limit]
        if not threads:
            return _text("No threads found")
        lines = [f"# Threads ({len(threads)})\n"]
        for t in threads:
            project_info = f" [project: `{t.project_id}`]" if t.project_id else ""
            summary_mark = " 📝" if t.summary else ""
            lines.append(
                f"- `{t.thread_id}` **{t.title or 'Untitled'}**{project_info}\n"
                f"  {len(t.messages)} msgs, updated {t.updated_at:%Y-%m-%d}{summary_mark}"
            )
        return _text("\n".join(lines))

    # ============ Concept Tools ============

    @mcp.tool()
    def search_concepts(
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> TextContent:
        """Find stored knowledge about users, topics, or entities using semantic search. Always call this before create_concept() to avoid duplicates. Returns concept IDs—use read_concept() for full content."""
        results = searcher.search_concepts(query, limit=limit, project_id=project_id)
        if not results:
            return _text(f"No concepts found for query: {query}")
        lines = [f"# Concept Search Results ({len(results)})\n"]
        for r in results:
            lines.append(f"- `{r['id']}` **{r['name']}** (score: {r['score']:.2f})")
        return _text("\n".join(lines))

    def _format_concept(concept) -> str:
        """Format a concept as markdown."""
        lines = [
            f"# {concept.name}",
            f"**Concept ID:** `{concept.concept_id}`",
        ]
        if concept.project_id:
            lines.append(f"**Project:** `{concept.project_id}`")
        if concept.tags:
            lines.append(f"**Tags:** {', '.join(concept.tags)}")
        lines.append(f"**Updated:** {concept.updated_at:%Y-%m-%d %H:%M}")
        if concept.text:
            lines.append(f"\n---\n\n{concept.text}")
        return "\n".join(lines)

    @mcp.tool()
    def read_concept(concept_id: str) -> TextContent:
        """Get the full content of a concept by its ID. Use after search_concepts() or list_concepts() to retrieve the complete markdown content."""
        concept = storage.load_concept(concept_id)
        if not concept:
            return _text(f"Concept {concept_id} not found")
        return _text(_format_concept(concept))

    @mcp.tool()
    def read_concept_by_name(name: str) -> TextContent:
        """Get a concept by its exact name. Faster than search when you know the exact name. Returns the full markdown content."""
        concept = storage.load_concept_by_name(name)
        if not concept:
            return _text(f"Concept '{name}' not found")
        return _text(_format_concept(concept))

    @mcp.tool()
    def create_concept(
        name: str,
        text: str = "",
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Store knowledge about users, topics, or entities as a named markdown document. Always search_concepts() first to check for existing entries—use update_concept() instead if one exists. Good for user preferences, facts, and domain knowledge."""
        concept = Concept(
            name=name,
            text=text,
            project_id=project_id,
            tags=tags or [],
        )
        storage.save(concept)
        # Add to search index
        searcher.add_to_index(
            "concept",
            f"{name}\n{text}",
            {
                "id": concept.concept_id,
                "name": name,
                "project_id": project_id,
            },
        )
        return {"concept_id": concept.concept_id, "created": True}

    @mcp.tool()
    def list_concepts(project_id: str | None = None) -> TextContent:
        """Browse all stored concepts. Use when you want to see everything available rather than searching for something specific. Returns names and IDs—use read_concept() to get full content."""
        concepts = storage.list_concepts(project_id=project_id)
        if not concepts:
            return _text("No concepts found")
        lines = [f"# Concepts ({len(concepts)})\n"]
        for c in concepts:
            project_info = f" [project: `{c.project_id}`]" if c.project_id else ""
            tags_info = f" ({', '.join(c.tags)})" if c.tags else ""
            lines.append(f"- `{c.concept_id}` **{c.name}**{project_info}{tags_info}")
        return _text("\n".join(lines))

    @mcp.tool()
    def update_concept(
        concept_id: str,
        name: str | None = None,
        text: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify an existing concept's content or metadata. Use to add new information to existing concepts rather than creating duplicates. Only provided fields are updated—omit fields to keep current values."""
        concept = storage.load_concept(concept_id)
        if not concept:
            return {"error": f"Concept {concept_id} not found"}

        if name is not None:
            concept.name = name
        if text is not None:
            concept.text = text
        if project_id is not None:
            concept.project_id = project_id
        if tags is not None:
            concept.tags = tags

        concept.updated_at = datetime.now()
        storage.save(concept)
        # Rebuild index to update embeddings
        searcher.build_index()
        return {"concept_id": concept_id, "updated": True}

    # ============ Reflection Tools ============

    @mcp.tool()
    def add_reflection(
        text: str,
        project_id: str | None = None,
        thread_id: str | None = None,
        skill_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Record a learning or insight from an error or corrective feedback. Use when something went wrong or could be improved—describe what happened and what to do differently. Link to skill_id if related to a specific procedure. Check read_reflections() before similar tasks."""
        reflection = Reflection(
            text=text,
            project_id=project_id,
            thread_id=thread_id,
            skill_id=skill_id,
            tags=tags or [],
        )
        storage.save(reflection)
        return {"reflection_id": reflection.reflection_id, "created": True}

    @mcp.tool()
    def read_reflections(
        project_id: str | None = None,
        skill_id: str | None = None,
    ) -> TextContent:
        """Review past learnings and insights to avoid repeating mistakes. Call before performing tasks where you've previously made errors. Filter by skill_id to see reflections for a specific procedure."""
        reflections = storage.list_reflections(project_id=project_id, skill_id=skill_id)
        if not reflections:
            return _text("No reflections found")
        lines = [f"# Reflections ({len(reflections)})\n"]
        for r in reflections:
            project_info = f" [project: `{r.project_id}`]" if r.project_id else ""
            skill_info = f" [skill: `{r.skill_id}`]" if r.skill_id else ""
            thread_info = f" [thread: `{r.thread_id}`]" if r.thread_id else ""
            tags_info = f" ({', '.join(r.tags)})" if r.tags else ""
            lines.append(
                f"## `{r.reflection_id}`{project_info}{skill_info}{thread_info}{tags_info}\n"
                f"{r.text}\n"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def update_reflection(
        reflection_id: str,
        text: str | None = None,
        project_id: str | None = None,
        thread_id: str | None = None,
        skill_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify an existing reflection's content or associations. Use to refine learnings or add context. Only provided fields are updated."""
        reflection = storage.load_reflection(reflection_id)
        if not reflection:
            return {"error": f"Reflection {reflection_id} not found"}

        if text is not None:
            reflection.text = text
        if project_id is not None:
            reflection.project_id = project_id
        if thread_id is not None:
            reflection.thread_id = thread_id
        if skill_id is not None:
            reflection.skill_id = skill_id
        if tags is not None:
            reflection.tags = tags

        reflection.updated_at = datetime.now()
        storage.save(reflection)
        return {"reflection_id": reflection.reflection_id, "updated": True}

    # ============ Project Tools ============

    @mcp.tool()
    def create_project(
        name: str,
        description: str = "",
        instructions: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Create a project to group related threads, concepts, and artifacts. Use to mirror project configuration from your IDE or workspace into persistent memory. Check list_projects() first to avoid duplicates."""
        project = Project(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags or [],
        )
        storage.save(project)
        return {"project_id": project.project_id, "created": True}

    @mcp.tool()
    def read_project(project_id: str) -> TextContent:
        """Get a project's full details including description and instructions. Use at the start of work sessions to load project-specific context and guidelines."""
        project = storage.load_project(project_id)
        if not project:
            return _text(f"Project {project_id} not found")
        lines = [
            f"# {project.name}",
            f"**Project ID:** `{project.project_id}`",
        ]
        if project.description:
            lines.append(f"**Description:** {project.description}")
        if project.tags:
            lines.append(f"**Tags:** {', '.join(project.tags)}")
        lines.append(f"**Updated:** {project.updated_at:%Y-%m-%d %H:%M}")
        if project.instructions:
            lines.append(f"\n---\n\n{project.instructions}")
        return _text("\n".join(lines))

    @mcp.tool()
    def list_projects() -> TextContent:
        """Browse all projects in memory. Use to find or verify project existence before creating a new one. Returns project IDs—use read_project() for full details."""
        projects = storage.list_projects()
        if not projects:
            return _text("No projects found")
        lines = [f"# Projects ({len(projects)})\n"]
        for p in projects:
            desc = f" - {p.description}" if p.description else ""
            tags_info = f" ({', '.join(p.tags)})" if p.tags else ""
            lines.append(f"- `{p.project_id}` **{p.name}**{tags_info}{desc}")
        return _text("\n".join(lines))

    @mcp.tool()
    def update_project(
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify a project's details. Use to sync changes from IDE or workspace configuration. Only provided fields are updated—omit fields to keep current values."""
        project = storage.load_project(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if instructions is not None:
            project.instructions = instructions
        if tags is not None:
            project.tags = tags

        project.updated_at = datetime.now()
        storage.save(project)
        return {"project_id": project.project_id, "updated": True}

    # ============ Skill Tools ============

    @mcp.tool()
    def create_skill(
        name: str,
        description: str = "",
        instructions: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Store a reusable procedure or workflow as markdown instructions. Use for recurring tasks, project-specific processes, or step-by-step guides. For large code (100+ lines), create linked Artifacts instead of embedding in instructions. Check search_skills() first to avoid duplicates."""
        skill = Skill(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags or [],
        )
        storage.save(skill)
        return {"skill_id": skill.skill_id, "created": True}

    @mcp.tool()
    def read_skill(skill_id: str) -> TextContent:
        """Get the full instructions for a skill. Use after search_skills() or list_skills() to retrieve the complete procedure. Also check read_reflections(skill_id=...) for past learnings about this skill."""
        skill = storage.load_skill(skill_id)
        if not skill:
            return _text(f"Skill {skill_id} not found")
        lines = [
            f"# {skill.name}",
            f"**Skill ID:** `{skill.skill_id}`",
        ]
        if skill.description:
            lines.append(f"**Description:** {skill.description}")
        if skill.tags:
            lines.append(f"**Tags:** {', '.join(skill.tags)}")
        lines.append(f"**Updated:** {skill.updated_at:%Y-%m-%d %H:%M}")
        if skill.instructions:
            lines.append(f"\n---\n\n{skill.instructions}")
        return _text("\n".join(lines))

    @mcp.tool()
    def list_skills() -> TextContent:
        """Browse all stored procedures and workflows. Returns skill names, descriptions, and IDs—use read_skill() to get full instructions."""
        skills = storage.list_skills()
        if not skills:
            return _text("No skills found")
        lines = [f"# Skills ({len(skills)})\n"]
        for s in skills:
            desc = f" - {s.description}" if s.description else ""
            tags_info = f" ({', '.join(s.tags)})" if s.tags else ""
            lines.append(f"- `{s.skill_id}` **{s.name}**{tags_info}{desc}")
        return _text("\n".join(lines))

    @mcp.tool()
    def search_skills(
        query: str,
        limit: int = 10,
    ) -> TextContent:
        """Find procedures and workflows using semantic search. Use when you need a skill for a specific task. Returns skill IDs—use read_skill() for full instructions."""
        results = searcher.search_skills(query, limit=limit)
        if not results:
            return _text(f"No skills found for query: {query}")
        lines = [f"# Skill Search Results ({len(results)})\n"]
        for r in results:
            skill = storage.load_skill(r["id"])
            if skill:
                desc = f" - {skill.description}" if skill.description else ""
                lines.append(
                    f"- `{r['id']}` **{skill.name}** (score: {r['score']:.2f}){desc}"
                )
        return _text("\n".join(lines))

    @mcp.tool()
    def update_skill(
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify a skill's instructions or metadata. Use to improve procedures based on experience. For code stored in linked Artifacts, use sync_artifact_from_disk() instead. Only provided fields are updated."""
        skill = storage.load_skill(skill_id)
        if not skill:
            return {"error": f"Skill {skill_id} not found"}

        if name is not None:
            skill.name = name
        if description is not None:
            skill.description = description
        if instructions is not None:
            skill.instructions = instructions
        if tags is not None:
            skill.tags = tags

        skill.updated_at = datetime.now()
        storage.save(skill)
        return {"skill_id": skill.skill_id, "updated": True}

    # ============ Artifact Tools ============

    @mcp.tool()
    def create_artifact(
        name: str,
        content: str = "",
        description: str = "",
        content_type: str = "markdown",
        path: str | None = None,
        skill_id: str | None = None,
        project_id: str | None = None,
        originating_thread_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Store a collaborative document that evolves through conversation—specs, code, designs, research. Set path (e.g., "scripts/helper.py") for file-based artifacts that can be written to disk. Link to skill_id to associate code with a procedure. Unlike concepts (knowledge), artifacts are work products."""
        artifact = Artifact(
            name=name,
            content=content,
            description=description,
            content_type=content_type,
            path=path,
            skill_id=skill_id,
            project_id=project_id,
            originating_thread_id=originating_thread_id,
            tags=tags or [],
        )
        storage.save(artifact)
        # Add to search index
        searcher.add_to_index(
            "artifact",
            f"{name}\n{description}\n{content}",
            {
                "id": artifact.artifact_id,
                "name": name,
                "project_id": project_id,
            },
        )
        return {"artifact_id": artifact.artifact_id, "created": True}

    @mcp.tool()
    def read_artifact(artifact_id: str) -> TextContent:
        """Get an artifact's full content and metadata. Use after search_artifacts() or list_artifacts() to retrieve the complete document for editing or reference."""
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return _text(f"Artifact {artifact_id} not found")
        lines = [
            f"# {artifact.name}",
            f"**Artifact ID:** `{artifact.artifact_id}`",
        ]
        if artifact.description:
            lines.append(f"**Description:** {artifact.description}")
        lines.append(f"**Type:** {artifact.content_type}")
        if artifact.path:
            lines.append(f"**Path:** `{artifact.path}`")
        if artifact.skill_id:
            lines.append(f"**Skill:** `{artifact.skill_id}`")
        if artifact.project_id:
            lines.append(f"**Project:** `{artifact.project_id}`")
        if artifact.originating_thread_id:
            lines.append(f"**Origin Thread:** `{artifact.originating_thread_id}`")
        if artifact.tags:
            lines.append(f"**Tags:** {', '.join(artifact.tags)}")
        lines.append(f"**Updated:** {artifact.updated_at:%Y-%m-%d %H:%M}")
        if artifact.content:
            lang = artifact.content_type if artifact.content_type != "markdown" else ""
            lines.append(f"\n---\n\n```{lang}\n{artifact.content}\n```")
        return _text("\n".join(lines))

    @mcp.tool()
    def update_artifact(
        artifact_id: str,
        name: str | None = None,
        content: str | None = None,
        description: str | None = None,
        content_type: str | None = None,
        path: str | None = None,
        skill_id: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify an artifact's content or metadata. Use to persist changes as you collaborate on documents. For code files edited on disk, use sync_artifact_from_disk() instead. Only provided fields are updated."""
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return {"error": f"Artifact {artifact_id} not found"}

        if name is not None:
            artifact.name = name
        if content is not None:
            artifact.content = content
        if description is not None:
            artifact.description = description
        if content_type is not None:
            artifact.content_type = content_type
        if path is not None:
            artifact.path = path
        if skill_id is not None:
            artifact.skill_id = skill_id
        if project_id is not None:
            artifact.project_id = project_id
        if tags is not None:
            artifact.tags = tags

        artifact.updated_at = datetime.now()
        storage.save(artifact)
        # Rebuild index to update embeddings
        searcher.build_index()
        return {"artifact_id": artifact.artifact_id, "updated": True}

    @mcp.tool()
    def list_artifacts(project_id: str | None = None) -> TextContent:
        """Browse all collaborative documents. Use when starting a project session to show available artifacts the user can continue working on. Returns artifact IDs—use read_artifact() for full content."""
        artifacts = storage.list_artifacts(project_id=project_id)
        if not artifacts:
            return _text("No artifacts found")
        lines = [f"# Artifacts ({len(artifacts)})\n"]
        for a in artifacts:
            desc = f" - {a.description}" if a.description else ""
            path_info = f" [`{a.path}`]" if a.path else ""
            lines.append(
                f"- `{a.artifact_id}` **{a.name}**{path_info} ({a.content_type}){desc}"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def search_artifacts(
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> TextContent:
        """Find collaborative documents by their content using semantic search. Returns artifact IDs—use read_artifact() to get the full document."""
        results = searcher.search_artifacts(query, limit=limit, project_id=project_id)
        if not results:
            return _text(f"No artifacts found for query: {query}")
        lines = [f"# Artifact Search Results ({len(results)})\n"]
        for r in results:
            lines.append(f"- `{r['id']}` **{r['name']}** (score: {r['score']:.2f})")
        return _text("\n".join(lines))

    @mcp.tool()
    def write_artifact_to_disk(
        artifact_id: str,
        target_dir: str,
    ) -> dict:
        """Export an artifact to the filesystem at target_dir/artifact.path. The artifact must have a path set. Creates parent directories as needed. Use to materialize code artifacts into a project."""
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return {"error": f"Artifact {artifact_id} not found"}

        if not artifact.path:
            return {"error": f"Artifact {artifact_id} has no path set"}

        target_path = Path(target_dir) / artifact.path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(artifact.content)

        return {"written": True, "path": str(target_path)}

    @mcp.tool()
    def sync_artifact_from_disk(
        artifact_id: str,
        source_path: str,
    ) -> dict:
        """Import file content from disk into an artifact. Use after editing code files externally to sync changes back to memory. The artifact's content is replaced with the file's content."""
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return {"error": f"Artifact {artifact_id} not found"}

        source = Path(source_path)
        if not source.exists():
            return {"error": f"File not found: {source_path}"}

        artifact.content = source.read_text()
        artifact.updated_at = datetime.now()
        storage.save(artifact)

        # Rebuild index to update embeddings
        searcher.build_index()

        return {"synced": True, "artifact_id": artifact_id}

    # ============ Index Management ============

    @mcp.tool()
    def rebuild_index() -> dict:
        """Regenerate the semantic search index from all stored content. Only needed if search results seem stale or after bulk imports. This is an expensive operation—use sparingly."""
        searcher.build_index()
        return {"rebuilt": True, "items": len(searcher._id_map)}

    return mcp
