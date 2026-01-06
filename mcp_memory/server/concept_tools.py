"""Concept tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Concept
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _format_concept, _text


def register_concept_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all concept-related tools with the MCP server."""

    @mcp.tool()
    def search_concepts(
        query: str,
        project_id: str | None = None,
        limit: int = 10,
        include_content: bool = False,
    ) -> TextContent:
        """Find stored knowledge using semantic search.

        Returns concept paths and IDs. Use read_concept_by_path() to navigate
        the hierarchy, or read_concept() with the ID for full content.

        Args:
            query: The search query.
            project_id: Optional project ID to filter results.
            limit: Maximum number of results to return.
            include_content: If True, include full content of matching concepts.
        """
        results = searcher.search_concepts(query, limit=limit, project_id=project_id)
        if not results:
            return _text(f"No concepts found for query: {query}")
        lines = [f"# Concept Search Results ({len(results)})\n"]
        for r in results:
            path = r.get("path", r["name"])
            lines.append(f"- `{r['id']}` **{path}** (score: {r['score']:.2f})")
            if include_content:
                concept = storage.load_concept(r["id"])
                if concept:
                    child_paths = storage.list_concept_child_paths(concept.full_path)
                    lines.append("")
                    lines.append(_format_concept(concept, child_paths=child_paths))
                    lines.append("")
        return _text("\n".join(lines))

    @mcp.tool()
    def read_concept(concept_id: str) -> TextContent:
        """Get the full content of a concept by its ID. Use after search_concepts() or list_concepts() to retrieve the complete markdown content."""
        concept = storage.load_concept(concept_id)
        if not concept:
            return _text(f"Concept {concept_id} not found")
        child_paths = storage.list_concept_child_paths(concept.full_path)
        return _text(_format_concept(concept, child_paths=child_paths))

    @mcp.tool()
    def read_many_concepts(concept_ids: list[str]) -> TextContent:
        """Read multiple concepts at once by their IDs.

        More efficient than calling read_concept() multiple times when you need
        to retrieve several concepts.

        Args:
            concept_ids: List of concept IDs to retrieve.

        Returns:
            Formatted content of all found concepts, with errors for missing ones.
        """
        if not concept_ids:
            return _text("No concept IDs provided")

        lines = [f"# Concepts ({len(concept_ids)} requested)\n"]
        found = 0
        for concept_id in concept_ids:
            concept = storage.load_concept(concept_id)
            if not concept:
                lines.append(f"## Error: Concept `{concept_id}` not found\n")
            else:
                found += 1
                child_paths = storage.list_concept_child_paths(concept.full_path)
                lines.append(_format_concept(concept, child_paths=child_paths))
                lines.append("\n---\n")

        lines.insert(1, f"**Found:** {found}/{len(concept_ids)}\n")
        return _text("\n".join(lines))

    @mcp.tool()
    def read_concept_by_name(name: str) -> TextContent:
        """Get a concept by its exact name (searches all levels). For hierarchical lookup, use read_concept_by_path() instead."""
        concept = storage.load_concept_by_name(name)
        if not concept:
            return _text(f"Concept '{name}' not found")
        child_paths = storage.list_concept_child_paths(concept.full_path)
        return _text(_format_concept(concept, child_paths=child_paths))

    @mcp.tool()
    def read_concept_by_path(path: str) -> TextContent:
        """Get a concept by its hierarchical path.

        Path format: "Parent/Child/Grandchild" (e.g., "Lane Harker/Characters/Lane")
        Use this to navigate the concept hierarchy. The output includes any children
        of this concept, so you can see the hierarchy structure in a single call.
        """
        concept = storage.load_concept_by_path(path)
        if not concept:
            return _text(f"Concept at path '{path}' not found")
        child_paths = storage.list_concept_child_paths(concept.full_path)
        return _text(_format_concept(concept, child_paths=child_paths))

    @mcp.tool()
    def list_concept_children(parent_path: str | None = None) -> TextContent:
        """List direct children of a concept path.

        Args:
            parent_path: Path to parent (e.g., "Andrew Brookins"). None for root-level concepts.

        Returns concepts that are direct children, not all descendants.
        Use this to navigate down the hierarchy.
        """
        children = storage.list_concept_children(parent_path)
        if not children:
            path_desc = f"'{parent_path}'" if parent_path else "root"
            return _text(f"No child concepts found under {path_desc}")

        path_desc = f"'{parent_path}'" if parent_path else "root"
        lines = [f"# Children of {path_desc} ({len(children)})\n"]
        for c in children:
            project_info = f" [project: `{c.project_id}`]" if c.project_id else ""
            tags_info = f" ({', '.join(c.tags)})" if c.tags else ""
            lines.append(
                f"- `{c.concept_id}` **{c.name}** → `{c.full_path}`{project_info}{tags_info}"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def create_concept(
        name: str,
        text: str = "",
        parent_path: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Store knowledge as a hierarchical concept.

        Args:
            name: The concept name (leaf name, not full path)
            text: Markdown content
            parent_path: Where to place this concept (e.g., "Lane Harker/Characters")
            project_id: Optional project association
            tags: Optional tags for categorization
            links: Optional cross-references to other concepts

        Examples:
            create_concept("Preferences", parent_path="Andrew Brookins", ...)
            create_concept("Lane", parent_path="Lane Harker/Characters", ...)
        """
        concept = Concept(
            name=name,
            text=text,
            parent_path=parent_path,
            project_id=project_id,
            tags=tags or [],
            links=links or [],
        )
        storage.save(concept)
        # Add to search index with full path
        full_path = concept.full_path
        searcher.add_to_index(
            "concept",
            f"{full_path}\n{name}\n{text}",
            {
                "id": concept.concept_id,
                "name": name,
                "path": full_path,
                "project_id": project_id,
            },
        )
        return {
            "concept_id": concept.concept_id,
            "path": full_path,
            "created": True,
        }

    @mcp.tool()
    def list_concepts(
        project_id: str | None = None, parent_path: str | None = None
    ) -> TextContent:
        """Browse all stored concepts, optionally filtered by parent path.

        Args:
            project_id: Filter by project
            parent_path: Filter to concepts under this path (e.g., "Andrew Brookins")

        For direct children only, use list_concept_children() instead.
        """
        concepts = storage.list_concepts(project_id=project_id, parent_path=parent_path)
        if not concepts:
            return _text("No concepts found")
        lines = [f"# Concepts ({len(concepts)})\n"]
        for c in concepts:
            project_info = f" [project: `{c.project_id}`]" if c.project_id else ""
            tags_info = f" ({', '.join(c.tags)})" if c.tags else ""
            # Show full path for clarity
            lines.append(
                f"- `{c.concept_id}` **{c.full_path}**{project_info}{tags_info}"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def update_concept(
        concept_id: str,
        name: str | None = None,
        text: str | None = None,
        parent_path: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Modify an existing concept's content or metadata.

        To move a concept to a different location, update parent_path.
        Only provided fields are updated—omit fields to keep current values.
        """
        concept = storage.load_concept(concept_id)
        if not concept:
            return {"error": f"Concept {concept_id} not found"}

        # Track if we need to move the file (name or parent_path changed)
        old_file_path = storage.find_concept_file(concept_id)
        old_name = concept.name
        old_parent_path = concept.parent_path

        if name is not None:
            concept.name = name
        if text is not None:
            concept.text = text
        if parent_path is not None:
            concept.parent_path = parent_path
        if project_id is not None:
            concept.project_id = project_id
        if tags is not None:
            concept.tags = tags
        if links is not None:
            concept.links = links

        concept.updated_at = datetime.now()

        # Check if file location changed (name or parent_path changed)
        name_changed = name is not None and name != old_name
        path_changed = parent_path is not None and parent_path != old_parent_path

        if (name_changed or path_changed) and old_file_path:
            # Delete old file before saving to new location
            storage.delete_concept_file(old_file_path)

        storage.save(concept)
        # Rebuild index to update embeddings
        searcher.build_index()
        return {"concept_id": concept_id, "path": concept.full_path, "updated": True}

    @mcp.tool()
    def delete_concept(concept_id: str) -> dict:
        """Delete a concept by its ID.

        This permanently removes the concept from storage and the search index.
        Use with caution—this action cannot be undone.

        Args:
            concept_id: The ID of the concept to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        concept = storage.load_concept(concept_id)
        if not concept:
            return {"error": f"Concept {concept_id} not found"}

        # Find and delete the file
        file_path = storage.find_concept_file(concept_id)
        if file_path:
            storage.delete_concept_file(file_path)

        # Rebuild index to remove the concept from search
        searcher.build_index()

        return {
            "concept_id": concept_id,
            "path": concept.full_path,
            "deleted": True,
        }
