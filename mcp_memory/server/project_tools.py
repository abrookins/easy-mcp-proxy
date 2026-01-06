"""Project tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Project
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_project_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all project-related tools with the MCP server."""

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

        # Track if we need to delete old file (name changed means new filename)
        old_name = project.name
        old_file_path = storage._find_file_by_id("Project", "project_id", project_id)

        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if instructions is not None:
            project.instructions = instructions
        if tags is not None:
            project.tags = tags

        project.updated_at = datetime.now()

        # Delete old file if name changed (new file will be created with new name)
        if name is not None and name != old_name and old_file_path:
            storage._delete_file(old_file_path)

        storage.save(project)
        return {"project_id": project.project_id, "updated": True}
