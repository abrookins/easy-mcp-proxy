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

