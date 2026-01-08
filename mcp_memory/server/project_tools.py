"""Project tools for MCP Memory server."""

# ruff: noqa: E501

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Project, utc_now
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_project_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all project-related tools with the MCP server."""

    @mcp.tool()
    def upsert_project(
        name: str | None = None,
        project_id: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create or update a project. If project_id is provided, updates the existing project. If not provided, creates a new project. Use to mirror project configuration from your IDE or workspace into persistent memory.

        Args:
            name: Project name (required for create, optional for update)
            project_id: If provided, update this project; otherwise create new
            description: Project description
            instructions: Project-specific guidelines and context
            tags: Tags for categorization
        """
        if project_id:
            # Update existing project
            project = storage.load_project(project_id)
            if not project:
                return {"error": f"Project {project_id} not found"}

            old_name = project.name
            old_file_path = storage._find_file_by_id(
                "Project", "project_id", project_id
            )

            if name is not None:
                project.name = name
            if description is not None:
                project.description = description
            if instructions is not None:
                project.instructions = instructions
            if tags is not None:
                project.tags = tags

            project.updated_at = utc_now()

            if name is not None and name != old_name and old_file_path:
                storage._delete_file(old_file_path)

            storage.save(project)
            return {"project_id": project.project_id, "updated": True}
        else:
            # Create new project - name is required
            if not name:
                return {"error": "name is required when creating a new project"}
            project = Project(
                name=name,
                description=description or "",
                instructions=instructions or "",
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
    def delete_project(project_id: str) -> dict:
        """Delete a project by its ID.

        This permanently removes the project from storage.
        Use with caution—this action cannot be undone.

        Note: This does not delete threads, concepts, or other entities
        associated with this project. Consider updating or removing
        those associations separately.

        Args:
            project_id: The ID of the project to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        project = storage.load_project(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}

        # Find and delete the file
        file_path = storage._find_file_by_id("Project", "project_id", project_id)
        if file_path:
            storage._delete_file(file_path)

        return {
            "project_id": project_id,
            "name": project.name,
            "deleted": True,
        }
