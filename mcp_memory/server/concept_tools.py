"""Concept tools for MCP Memory server."""

# ruff: noqa: E501

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Concept, utc_now
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _format_concept, _text


def register_concept_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all concept-related tools with the MCP server."""

    @mcp.tool()
    def find_concepts(
        query: str | None = None,
        project_id: str | None = None,
        parent_path: str | None = None,
        limit: int = 10,
        include_content: bool = False,
    ) -> TextContent:
        """Find or list concepts. With query: semantic search. Without: list all.

        Args:
            query: Semantic search query. If None, lists all concepts.
            project_id: Filter by project.
            parent_path: Filter to concepts under this path (list mode only).
            limit: Max results for search (default 10).
            include_content: If True, include full content in search results.

        Examples:
            find_concepts()  # List all concepts
            find_concepts(project_id="proj_123")  # List concepts in project
            find_concepts(query="authentication")  # Search for concepts
        """
        if query:
            # Semantic search mode
            results = searcher.search_concepts(
                query, limit=limit, project_id=project_id
            )
            if not results:
                return _text(f"No concepts found for query: {query}")
            lines = [f"# Concept Search Results ({len(results)})\n"]
            for r in results:
                path = r.get("path", r["name"])
                lines.append(f"- `{r['id']}` **{path}** (score: {r['score']:.2f})")
                if include_content:
                    concept = storage.load_concept(r["id"])
                    if concept:
                        child_paths = storage.list_concept_child_paths(
                            concept.full_path
                        )
                        lines.append("")
                        lines.append(_format_concept(concept, child_paths=child_paths))
                        lines.append("")
            return _text("\n".join(lines))
        else:
            # List mode
            concepts = storage.list_concepts(
                project_id=project_id, parent_path=parent_path
            )
            if not concepts:
                return _text("No concepts found")
            lines = [f"# Concepts ({len(concepts)})\n"]
            for c in concepts:
                project_info = f" [project: `{c.project_id}`]" if c.project_id else ""
                tags_info = f" ({', '.join(c.tags)})" if c.tags else ""
                lines.append(
                    f"- `{c.concept_id}` **{c.full_path}**{project_info}{tags_info}"
                )
            return _text("\n".join(lines))

    @mcp.tool()
    def get_concept(
        id: str | None = None,
        ids: list[str] | None = None,
        name: str | None = None,
        path: str | None = None,
        children_of: str | None = None,
        list_children: bool = False,
    ) -> TextContent:
        """Retrieve concepts by ID, name, path, or list children. Provide exactly one lookup parameter.

        Args:
            id: Get a single concept by its ID
            ids: Get multiple concepts by their IDs (batch retrieval)
            name: Get a concept by its exact name (searches all levels)
            path: Get a concept by its hierarchical path (e.g., "Lane Harker/Characters")
            children_of: List direct children of this path (use with list_children=True)
            list_children: If True with children_of, lists children; if True alone, lists root concepts

        Examples:
            get_concept(id="c_abc123")
            get_concept(ids=["c_abc", "c_def"])
            get_concept(name="Lane Harker")
            get_concept(path="Lane Harker/Characters/Lane")
            get_concept(list_children=True)  # List root concepts
            get_concept(children_of="Lane Harker", list_children=True)  # List children
        """
        # Count how many lookup methods were provided
        lookups = sum(
            [
                id is not None,
                ids is not None,
                name is not None,
                path is not None,
                list_children,
            ]
        )

        if lookups == 0:
            return _text(
                "Please provide one of: id, ids, name, path, or list_children=True"
            )
        if lookups > 1 and not (list_children and children_of is not None):
            return _text(
                "Please provide only one lookup method (id, ids, name, path, or list_children)"
            )

        # Get by ID
        if id is not None:
            concept = storage.load_concept(id)
            if not concept:
                return _text(f"Concept {id} not found")
            child_paths = storage.list_concept_child_paths(concept.full_path)
            return _text(_format_concept(concept, child_paths=child_paths))

        # Get multiple by IDs
        if ids is not None:
            if not ids:
                return _text("No concept IDs provided")
            lines = [f"# Concepts ({len(ids)} requested)\n"]
            found = 0
            for concept_id in ids:
                concept = storage.load_concept(concept_id)
                if not concept:
                    lines.append(f"## Error: Concept `{concept_id}` not found\n")
                else:
                    found += 1
                    child_paths = storage.list_concept_child_paths(concept.full_path)
                    lines.append(_format_concept(concept, child_paths=child_paths))
                    lines.append("\n---\n")
            lines.insert(1, f"**Found:** {found}/{len(ids)}\n")
            return _text("\n".join(lines))

        # Get by name
        if name is not None:
            concept = storage.load_concept_by_name(name)
            if not concept:
                return _text(f"Concept '{name}' not found")
            child_paths = storage.list_concept_child_paths(concept.full_path)
            return _text(_format_concept(concept, child_paths=child_paths))

        # Get by path
        if path is not None:
            concept = storage.load_concept_by_path(path)
            if not concept:
                return _text(f"Concept at path '{path}' not found")
            child_paths = storage.list_concept_child_paths(concept.full_path)
            return _text(_format_concept(concept, child_paths=child_paths))

        # List children
        if list_children:
            children = storage.list_concept_children(children_of)
            if not children:
                path_desc = f"'{children_of}'" if children_of else "root"
                return _text(f"No child concepts found under {path_desc}")
            path_desc = f"'{children_of}'" if children_of else "root"
            lines = [f"# Children of {path_desc} ({len(children)})\n"]
            for c in children:
                project_info = f" [project: `{c.project_id}`]" if c.project_id else ""
                tags_info = f" ({', '.join(c.tags)})" if c.tags else ""
                lines.append(
                    f"- `{c.concept_id}` **{c.name}** → `{c.full_path}`{project_info}{tags_info}"
                )
            return _text("\n".join(lines))

        return _text("Invalid request")

    @mcp.tool()
    def upsert_concept(
        name: str | None = None,
        concept_id: str | None = None,
        text: str | None = None,
        parent_path: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
    ) -> dict:
        """Create or update a hierarchical concept (knowledge storage). If concept_id is provided, updates the existing concept. If not provided, creates a new concept.

        Args:
            name: The concept name (required for create, optional for update)
            concept_id: If provided, update this concept; otherwise create new
            text: Markdown content
            parent_path: Where to place this concept (e.g., "Lane Harker/Characters")
            project_id: Optional project association
            tags: Optional tags for categorization
            links: Optional cross-references to other concepts

        Examples:
            upsert_concept(name="Preferences", parent_path="Andrew Brookins", ...)
            upsert_concept(concept_id="c_123", text="Updated text")
        """
        if concept_id:
            # Update existing concept
            concept = storage.load_concept(concept_id)
            if not concept:
                return {"error": f"Concept {concept_id} not found"}

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

            concept.updated_at = utc_now()

            name_changed = name is not None and name != old_name
            path_changed = parent_path is not None and parent_path != old_parent_path

            if (name_changed or path_changed) and old_file_path:
                storage.delete_concept_file(old_file_path)

            storage.save(concept)
            searcher.build_index()
            return {
                "concept_id": concept_id,
                "path": concept.full_path,
                "updated": True,
            }
        else:
            # Create new concept - name is required
            if not name:
                return {"error": "name is required when creating a new concept"}
            concept = Concept(
                name=name,
                text=text or "",
                parent_path=parent_path,
                project_id=project_id,
                tags=tags or [],
                links=links or [],
            )
            storage.save(concept)
            full_path = concept.full_path
            searcher.add_to_index(
                "concept",
                f"{full_path}\n{name}\n{text or ''}",
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
