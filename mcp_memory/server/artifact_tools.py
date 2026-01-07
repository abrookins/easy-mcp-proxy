"""Artifact tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Artifact
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_artifact_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all artifact-related tools with the MCP server."""

    @mcp.tool()
    def upsert_artifact(
        name: str | None = None,
        artifact_id: str | None = None,
        content: str | None = None,
        description: str | None = None,
        content_type: str | None = None,
        path: str | None = None,
        skill_id: str | None = None,
        project_id: str | None = None,
        originating_thread_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create or update a collaborative document (specs, code, designs, research). If artifact_id is provided, updates the existing artifact. If not provided, creates a new artifact. Set path (e.g., "scripts/helper.py") for file-based artifacts. Link to skill_id to associate code with a procedure.

        Args:
            name: Artifact name (required for create, optional for update)
            artifact_id: If provided, update this artifact; otherwise create new
            content: The artifact content
            description: Description of the artifact
            content_type: Type of content (markdown, python, etc.)
            path: File path for disk export (e.g., "scripts/helper.py")
            skill_id: Link to a skill that uses this artifact
            project_id: Associate with a project
            originating_thread_id: Thread where this artifact was created
            tags: Tags for categorization
        """
        if artifact_id:
            # Update existing artifact
            artifact = storage.load_artifact(artifact_id)
            if not artifact:
                return {"error": f"Artifact {artifact_id} not found"}

            old_name = artifact.name
            old_file_path = storage._find_file_by_id(
                "Artifact", "artifact_id", artifact_id
            )

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

            if name is not None and name != old_name and old_file_path:
                storage._delete_file(old_file_path)

            storage.save(artifact)
            searcher.build_index()
            return {"artifact_id": artifact.artifact_id, "updated": True}
        else:
            # Create new artifact - name is required
            if not name:
                return {"error": "name is required when creating a new artifact"}
            artifact = Artifact(
                name=name,
                content=content or "",
                description=description or "",
                content_type=content_type or "markdown",
                path=path,
                skill_id=skill_id,
                project_id=project_id,
                originating_thread_id=originating_thread_id,
                tags=tags or [],
            )
            storage.save(artifact)
            # Add to search index (include path and tags for better discovery)
            index_parts = [name, description or "", content or ""]
            if path:
                index_parts.insert(0, path)
            if tags:
                index_parts.append(" ".join(tags))
            searcher.add_to_index(
                "artifact",
                "\n".join(index_parts),
                {
                    "id": artifact.artifact_id,
                    "name": name,
                    "path": path,
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
    def find_artifacts(
        query: str | None = None, project_id: str | None = None, limit: int = 10
    ) -> TextContent:
        """Find or list artifacts. With query: semantic search. Without: list all.

        Args:
            query: Semantic search query. If None, lists all artifacts.
            project_id: Filter by project.
            limit: Max results for search (default 10).

        Examples:
            find_artifacts()  # List all artifacts
            find_artifacts(project_id="proj_123")  # List artifacts in project
            find_artifacts(query="database schema")  # Search artifacts
        """
        if query:
            # Semantic search mode
            results = searcher.search_artifacts(
                query, limit=limit, project_id=project_id
            )
            if not results:
                return _text(f"No artifacts found for query: {query}")
            lines = [f"# Artifact Search Results ({len(results)})\n"]
            for r in results:
                lines.append(f"- `{r['id']}` **{r['name']}** (score: {r['score']:.2f})")
            return _text("\n".join(lines))
        else:
            # List mode
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

    @mcp.tool()
    def delete_artifact(artifact_id: str) -> dict:
        """Delete an artifact by its ID.

        This permanently removes the artifact from storage and the search index.
        Use with caution—this action cannot be undone.

        Args:
            artifact_id: The ID of the artifact to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        artifact = storage.load_artifact(artifact_id)
        if not artifact:
            return {"error": f"Artifact {artifact_id} not found"}

        # Find and delete the file
        file_path = storage._find_file_by_id("Artifact", "artifact_id", artifact_id)
        if file_path:
            storage._delete_file(file_path)

        # Rebuild index to remove the artifact from search
        searcher.build_index()

        return {
            "artifact_id": artifact_id,
            "name": artifact.name,
            "deleted": True,
        }
