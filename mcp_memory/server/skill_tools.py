"""Skill tools for MCP Memory server."""

# ruff: noqa: E501

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Skill, utc_now
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_skill_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all skill-related tools with the MCP server."""

    @mcp.tool()
    def upsert_skill(
        name: str | None = None,
        skill_id: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create or update a skill (reusable procedure/workflow). If skill_id is provided, updates the existing skill. If not provided, creates a new skill. For large code (100+ lines), create linked Artifacts instead of embedding in instructions.

        Args:
            name: Skill name (required for create, optional for update)
            skill_id: If provided, update this skill; otherwise create new
            description: Description of what this skill does
            instructions: Markdown instructions for the procedure
            tags: Tags for categorization
        """
        if skill_id:
            # Update existing skill
            skill = storage.load_skill(skill_id)
            if not skill:
                return {"error": f"Skill {skill_id} not found"}

            old_name = skill.name
            old_file_path = storage._find_file_by_id("Skill", "skill_id", skill_id)

            if name is not None:
                skill.name = name
            if description is not None:
                skill.description = description
            if instructions is not None:
                skill.instructions = instructions
            if tags is not None:
                skill.tags = tags

            skill.updated_at = utc_now()

            if name is not None and name != old_name and old_file_path:
                storage._delete_file(old_file_path)

            storage.save(skill)
            # Rebuild index to update embeddings
            searcher.build_index()
            return {"skill_id": skill.skill_id, "updated": True}
        else:
            # Create new skill - name is required
            if not name:
                return {"error": "name is required when creating a new skill"}
            skill = Skill(
                name=name,
                description=description or "",
                instructions=instructions or "",
                tags=tags or [],
            )
            storage.save(skill)
            # Add to search index (include tags for better discovery)
            index_parts = [name, description or "", instructions or ""]
            if tags:
                index_parts.append(" ".join(tags))
            searcher.add_to_index(
                "skill",
                "\n".join(index_parts),
                {"id": skill.skill_id, "name": name},
            )
            return {"skill_id": skill.skill_id, "created": True}

    @mcp.tool()
    def read_skill(skill_id: str) -> TextContent:
        """Get the full instructions for a skill. Use after search_skills() or list_skills() to retrieve the complete procedure. Also check read_reflections(skill_id=...) for past learnings about this skill."""
        skill = storage.load_skill(skill_id)
        if not skill:
            return _text(f"Skill {skill_id} not found")
        lines = [
            f"# {skill.name}",
            f"**Skill ID:** `{skill.skill_id}`",
        ]
        if skill.description:
            lines.append(f"**Description:** {skill.description}")
        if skill.tags:
            lines.append(f"**Tags:** {', '.join(skill.tags)}")
        lines.append(f"**Updated:** {skill.updated_at:%Y-%m-%d %H:%M}")
        if skill.instructions:
            lines.append(f"\n---\n\n{skill.instructions}")
        return _text("\n".join(lines))

    @mcp.tool()
    def find_skills(query: str | None = None, limit: int = 10) -> TextContent:
        """Find or list skills. With query: semantic search. Without: list all.

        Args:
            query: Semantic search query. If None, lists all skills.
            limit: Max results for search (default 10).

        Examples:
            find_skills()  # List all skills
            find_skills(query="deploy to production")  # Search skills
        """
        if query:
            # Semantic search mode
            results = searcher.search_skills(query, limit=limit)
            if not results:
                return _text(f"No skills found for query: {query}")
            lines = [f"# Skill Search Results ({len(results)})\n"]
            for r in results:
                skill = storage.load_skill(r["id"])
                if skill:
                    desc = f" - {skill.description}" if skill.description else ""
                    lines.append(
                        f"- `{r['id']}` **{skill.name}** (score: {r['score']:.2f}){desc}"
                    )
            return _text("\n".join(lines))
        else:
            # List mode
            skills = storage.list_skills()
            if not skills:
                return _text("No skills found")
            lines = [f"# Skills ({len(skills)})\n"]
            for s in skills:
                desc = f" - {s.description}" if s.description else ""
                tags_info = f" ({', '.join(s.tags)})" if s.tags else ""
                lines.append(f"- `{s.skill_id}` **{s.name}**{tags_info}{desc}")
            return _text("\n".join(lines))

    @mcp.tool()
    def delete_skill(skill_id: str) -> dict:
        """Delete a skill by its ID.

        This permanently removes the skill from storage and the search index.
        Use with caution—this action cannot be undone.

        Args:
            skill_id: The ID of the skill to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        skill = storage.load_skill(skill_id)
        if not skill:
            return {"error": f"Skill {skill_id} not found"}

        # Find and delete the file
        file_path = storage._find_file_by_id("Skill", "skill_id", skill_id)
        if file_path:
            storage._delete_file(file_path)

        # Rebuild index to remove the skill from search
        searcher.build_index()

        return {
            "skill_id": skill_id,
            "name": skill.name,
            "deleted": True,
        }
