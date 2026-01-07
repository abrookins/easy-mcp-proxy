"""Reflection tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Reflection
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_reflection_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all reflection-related tools with the MCP server."""

    @mcp.tool()
    def upsert_reflection(
        text: str | None = None,
        reflection_id: str | None = None,
        project_id: str | None = None,
        thread_id: str | None = None,
        skill_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create or update a reflection (learning/insight from errors or feedback). If reflection_id is provided, updates the existing reflection. If not provided, creates a new reflection. Link to skill_id if related to a specific procedure.

        Args:
            text: The reflection content (required for create, optional for update)
            reflection_id: If provided, update this reflection; otherwise create new
            project_id: Associate with a project
            thread_id: Link to the conversation where this occurred
            skill_id: Link to a skill/procedure this relates to
            tags: Tags for categorization
        """
        if reflection_id:
            # Update existing reflection
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
        else:
            # Create new reflection - text is required
            if not text:
                return {"error": "text is required when creating a new reflection"}
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
    def delete_reflection(reflection_id: str) -> dict:
        """Delete a reflection by its ID.

        This permanently removes the reflection from storage.
        Use with caution—this action cannot be undone.

        Args:
            reflection_id: The ID of the reflection to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        reflection = storage.load_reflection(reflection_id)
        if not reflection:
            return {"error": f"Reflection {reflection_id} not found"}

        # Find and delete the file
        file_path = storage._find_file_by_id(
            "Reflection", "reflection_id", reflection_id
        )
        if file_path:
            storage._delete_file(file_path)

        return {
            "reflection_id": reflection_id,
            "deleted": True,
        }
