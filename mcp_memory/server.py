"""MCP Server for the memory system.

Provides tools for managing threads, concepts, projects, skills, and reflections.
"""

from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

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
) -> FastMCP:
    """Create an MCP server with memory tools.

    Args:
        base_path: Base path for storage (ignored if config provided)
        name: Name for the MCP server
        config: Optional MemoryConfig (if not provided, uses base_path)
    """
    if config is None:
        config = MemoryConfig(base_path=base_path)
    storage = MemoryStorage(config)
    searcher = MemorySearcher(storage, config)

    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS)

    # ============ Thread Tools ============

    @mcp.tool()
    def create_thread(
        project_id: str | None = None,
        thread_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Create a new conversation thread.

        Args:
            project_id: Optional project to associate with this thread
            thread_id: Optional custom thread ID (auto-generated if not provided)
            title: Optional human-friendly title (auto-derived from first message if not provided)
        """
        thread = Thread(project_id=project_id, title=title)
        if thread_id:
            thread.thread_id = thread_id
        storage.save(thread)
        return {"thread_id": thread.thread_id, "title": thread.title, "created": True}

    @mcp.tool()
    def read_thread(
        thread_id: str,
        messages_from: str | None = None,
    ) -> dict:
        """Read a thread and its messages.

        Args:
            thread_id: The thread ID to read
            messages_from: Optional ISO timestamp to filter messages from
        """
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        messages = thread.messages
        if messages_from:
            from_dt = datetime.fromisoformat(messages_from)
            messages = [m for m in messages if m.timestamp >= from_dt]

        return {
            "thread_id": thread.thread_id,
            "title": thread.title,
            "project_id": thread.project_id,
            "summary": thread.summary,
            "messages": [m.model_dump(mode="json") for m in messages],
        }

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
        """Add messages to a thread.

        Args:
            thread_id: The thread to add messages to
            messages: List of messages with 'role' and 'text' fields
        """
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
    ) -> dict:
        """Search messages by semantic similarity.

        Args:
            query: Search query text
            thread_id: Optional thread to search within
            project_id: Optional project to filter by
            limit: Maximum results to return
        """
        results = searcher.search_messages(
            query, limit=limit, thread_id=thread_id, project_id=project_id
        )
        return {"results": results}

    @mcp.tool()
    def search_threads(query: str, limit: int = 10) -> dict:
        """Search threads by their message content.

        Args:
            query: Search query text
            limit: Maximum results to return
        """
        results = searcher.search_threads(query, limit=limit)
        return {"results": results}

    @mcp.tool()
    def compact_thread(thread_id: str, summary: str) -> dict:
        """Compact a thread by replacing messages with a summary.

        Args:
            thread_id: The thread to compact
            summary: Summary text to replace messages with
        """
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        thread.summary = summary
        thread.messages = []  # Clear messages after summarizing
        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "compacted": True}

    @mcp.tool()
    def list_threads(project_id: str | None = None, limit: int = 50) -> dict:
        """List all threads, optionally filtered by project.

        Args:
            project_id: Optional project to filter by
            limit: Maximum number of threads to return
        """
        threads = storage.list_threads(project_id=project_id)
        # Sort by updated_at descending
        threads.sort(key=lambda t: t.updated_at, reverse=True)
        threads = threads[:limit]
        return {
            "threads": [
                {
                    "thread_id": t.thread_id,
                    "title": t.title,
                    "project_id": t.project_id,
                    "message_count": len(t.messages),
                    "has_summary": t.summary is not None,
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in threads
            ]
        }

    # ============ Concept Tools ============

    @mcp.tool()
    def search_concepts(
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search concepts by semantic similarity.

        Args:
            query: Search query text
            project_id: Optional project to filter by
            limit: Maximum results to return
        """
        results = searcher.search_concepts(query, limit=limit, project_id=project_id)
        return {"results": results}

    @mcp.tool()
    def read_concept(concept_id: str) -> dict:
        """Read a concept by ID.

        Args:
            concept_id: The concept ID to read
        """
        concept = storage.load_concept(concept_id)
        if not concept:
            return {"error": f"Concept {concept_id} not found"}
        return concept.model_dump(mode="json")

    @mcp.tool()
    def read_concept_by_name(name: str) -> dict:
        """Read a concept by name.

        Args:
            name: The concept name to read
        """
        concept = storage.load_concept_by_name(name)
        if not concept:
            return {"error": f"Concept '{name}' not found"}
        return concept.model_dump(mode="json")

    @mcp.tool()
    def create_concept(
        name: str,
        text: str = "",
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create a new concept.

        Args:
            name: Name of the concept
            text: Markdown content for the concept
            project_id: Optional project association
            tags: Optional list of tags
        """
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
    def list_concepts(project_id: str | None = None) -> dict:
        """List all concepts, optionally filtered by project.

        Args:
            project_id: Optional project to filter by
        """
        concepts = storage.list_concepts(project_id=project_id)
        return {
            "concepts": [
                {
                    "concept_id": c.concept_id,
                    "name": c.name,
                    "project_id": c.project_id,
                    "tags": c.tags,
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in concepts
            ]
        }

    @mcp.tool()
    def update_concept(
        concept_id: str,
        name: str | None = None,
        text: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing concept.

        Args:
            concept_id: The concept ID to update
            name: New name (optional)
            text: New markdown content (optional)
            project_id: New project association (optional)
            tags: New tags (optional)
        """
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
        """Add a new reflection.

        Args:
            text: The reflection content (markdown)
            project_id: Optional project association
            thread_id: Optional thread association
            skill_id: Optional skill association
            tags: Optional list of tags
        """
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
    ) -> dict:
        """Read reflections, optionally filtered by project or skill.

        Args:
            project_id: Optional project to filter by
            skill_id: Optional skill to filter by
        """
        reflections = storage.list_reflections(project_id=project_id, skill_id=skill_id)
        return {"reflections": [r.model_dump(mode="json") for r in reflections]}

    @mcp.tool()
    def update_reflection(
        reflection_id: str,
        text: str | None = None,
        project_id: str | None = None,
        thread_id: str | None = None,
        skill_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing reflection.

        Args:
            reflection_id: The reflection ID to update
            text: New text content (optional)
            project_id: New project association (optional)
            thread_id: New thread association (optional)
            skill_id: New skill association (optional)
            tags: New tags (optional)
        """
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
        """Create a new project.

        Args:
            name: Project name
            description: Short description
            instructions: Markdown instructions for the project
            tags: Optional list of tags
        """
        project = Project(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags or [],
        )
        storage.save(project)
        return {"project_id": project.project_id, "created": True}

    @mcp.tool()
    def read_project(project_id: str) -> dict:
        """Read a project by ID.

        Args:
            project_id: The project ID to read
        """
        project = storage.load_project(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}
        return project.model_dump(mode="json")

    @mcp.tool()
    def list_projects() -> dict:
        """List all projects."""
        projects = storage.list_projects()
        return {"projects": [p.model_dump(mode="json") for p in projects]}

    @mcp.tool()
    def update_project(
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing project.

        Args:
            project_id: The project ID to update
            name: New name (optional)
            description: New description (optional)
            instructions: New instructions content (optional)
            tags: New tags (optional)
        """
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
        """Create a new skill.

        For small code snippets, include them directly in the instructions.
        For larger code files (100+ lines), use Artifacts linked via skill_id.

        Args:
            name: Skill name
            description: Short description
            instructions: Markdown instructions (reference Artifacts for large code)
            tags: Optional list of tags
        """
        skill = Skill(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags or [],
        )
        storage.save(skill)
        return {"skill_id": skill.skill_id, "created": True}

    @mcp.tool()
    def read_skill(skill_id: str) -> dict:
        """Read a skill by ID.

        Args:
            skill_id: The skill ID to read
        """
        skill = storage.load_skill(skill_id)
        if not skill:
            return {"error": f"Skill {skill_id} not found"}
        return skill.model_dump(mode="json")

    @mcp.tool()
    def list_skills() -> dict:
        """List all skills with their names and descriptions.

        Returns a compact summary for each skill. Use read_skill() to get
        the full instructions content.
        """
        skills = storage.list_skills()
        return {
            "skills": [
                {
                    "skill_id": s.skill_id,
                    "name": s.name,
                    "description": s.description,
                    "tags": s.tags,
                }
                for s in skills
            ]
        }

    @mcp.tool()
    def search_skills(
        query: str,
        limit: int = 10,
    ) -> dict:
        """Search skills by semantic similarity.

        Args:
            query: Search query text
            limit: Maximum results to return
        """
        results = searcher.search_skills(query, limit=limit)
        # Enrich results with skill name from storage
        enriched = []
        for r in results:
            skill = storage.load_skill(r["id"])
            if skill:
                enriched.append(
                    {
                        "skill_id": r["id"],
                        "name": skill.name,
                        "description": skill.description,
                        "score": r["score"],
                    }
                )
        return {"results": enriched}

    @mcp.tool()
    def update_skill(
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing skill.

        For code stored in linked Artifacts, use sync_artifact_from_disk() instead.

        Args:
            skill_id: The skill ID to update
            name: New name (optional)
            description: New description (optional)
            instructions: New instructions content (optional)
            tags: New tags (optional)
        """
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
        """Create a new artifact (collaborative document).

        For code artifacts that represent files, use `path` to specify the relative
        path (e.g., "scripts/helper.py"). Use `skill_id` to link artifacts to Skills.

        Args:
            name: Human-readable title for the artifact
            content: The artifact content (markdown by default)
            description: Brief description of the artifact's purpose
            content_type: Type of content (markdown, code, json, yaml, etc.)
            path: Relative path for file-based artifacts (e.g., "scripts/helper.py")
            skill_id: Optional link to parent Skill
            project_id: Optional project to associate with
            originating_thread_id: Optional thread where this artifact was created
            tags: Optional list of tags
        """
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
    def read_artifact(artifact_id: str) -> dict:
        """Read an artifact by ID.

        Args:
            artifact_id: The artifact ID to read
        """
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return {"error": f"Artifact {artifact_id} not found"}
        return artifact.model_dump(mode="json")

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
        """Update an existing artifact.

        Args:
            artifact_id: The artifact ID to update
            name: New name (optional)
            content: New content (optional)
            description: New description (optional)
            content_type: New content type (optional)
            path: New path for file-based artifacts (optional)
            skill_id: New skill association (optional)
            project_id: New project association (optional)
            tags: New tags (optional)
        """
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
    def list_artifacts(project_id: str | None = None) -> dict:
        """List all artifacts, optionally filtered by project.

        Returns a compact summary for each artifact. Use read_artifact() to get
        the full content.

        Args:
            project_id: Optional project to filter by
        """
        artifacts = storage.list_artifacts(project_id=project_id)
        return {
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "name": a.name,
                    "description": a.description,
                    "content_type": a.content_type,
                    "project_id": a.project_id,
                    "originating_thread_id": a.originating_thread_id,
                    "tags": a.tags,
                    "updated_at": a.updated_at.isoformat(),
                }
                for a in artifacts
            ]
        }

    @mcp.tool()
    def search_artifacts(
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search artifacts by semantic similarity.

        Args:
            query: Search query text
            project_id: Optional project to filter by
            limit: Maximum results to return
        """
        results = searcher.search_artifacts(query, limit=limit, project_id=project_id)
        return {"results": results}

    @mcp.tool()
    def write_artifact_to_disk(
        artifact_id: str,
        target_dir: str,
    ) -> dict:
        """Write an artifact to disk at target_dir/artifact.path.

        The artifact must have a `path` set. The file will be written to
        `target_dir/path`, creating any necessary parent directories.

        Args:
            artifact_id: The artifact ID to write
            target_dir: Base directory to write the file to
        """
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
        """Sync an artifact's content from a file on disk.

        Reads the file at `source_path` and updates the artifact's content.
        Use this after modifying code files to sync changes back to the artifact.

        Args:
            artifact_id: The artifact ID to update
            source_path: Path to the file to read content from
        """
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
        """Rebuild the search index from all content."""
        searcher.build_index()
        return {"rebuilt": True, "items": len(searcher._id_map)}

    return mcp
