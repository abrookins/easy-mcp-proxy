"""MCP Server for the memory system.

Provides tools for managing threads, concepts, projects, skills, and reflections.
"""

from datetime import datetime
from typing import Any

from fastmcp import FastMCP

from mcp_memory.models import (
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

    mcp = FastMCP(name)

    # ============ Thread Tools ============

    @mcp.tool()
    def create_thread(
        project_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict:
        """Create a new conversation thread.

        Args:
            project_id: Optional project to associate with this thread
            thread_id: Optional custom thread ID (auto-generated if not provided)
        """
        thread = Thread(project_id=project_id)
        if thread_id:
            thread.thread_id = thread_id
        storage.save(thread)
        return {"thread_id": thread.thread_id, "created": True}

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
            "project_id": thread.project_id,
            "summary": thread.summary,
            "messages": [m.model_dump(mode="json") for m in messages],
        }

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
            msg = Message(
                role=msg_data["role"],
                text=msg_data["text"],
                timestamp=datetime.fromisoformat(msg_data.get("timestamp", datetime.now().isoformat())),
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

        Args:
            name: Skill name
            description: Short description
            instructions: Markdown instructions for the skill
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
    def update_skill(
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing skill.

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

    # ============ Index Management ============

    @mcp.tool()
    def rebuild_index() -> dict:
        """Rebuild the search index from all content."""
        searcher.build_index()
        return {"rebuilt": True, "items": len(searcher._id_map)}

    return mcp

