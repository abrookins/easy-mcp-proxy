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
