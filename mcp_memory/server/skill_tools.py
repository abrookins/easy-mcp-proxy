"""Skill tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Skill
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def register_skill_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all skill-related tools with the MCP server."""

    @mcp.tool()
    def create_skill(
        name: str,
        description: str = "",
        instructions: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        """Store a reusable procedure or workflow as markdown instructions. Use for recurring tasks, project-specific processes, or step-by-step guides. For large code (100+ lines), create linked Artifacts instead of embedding in instructions. Check search_skills() first to avoid duplicates."""
        skill = Skill(
            name=name,
            description=description,
            instructions=instructions,
            tags=tags or [],
        )
        storage.save(skill)
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
    def list_skills() -> TextContent:
        """Browse all stored procedures and workflows. Returns skill names, descriptions, and IDs—use read_skill() to get full instructions."""
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
    def search_skills(
        query: str,
        limit: int = 10,
    ) -> TextContent:
        """Find procedures and workflows using semantic search. Use when you need a skill for a specific task. Returns skill IDs—use read_skill() for full instructions."""
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

    @mcp.tool()
    def update_skill(
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Modify a skill's instructions or metadata. Use to improve procedures based on experience. For code stored in linked Artifacts, use sync_artifact_from_disk() instead. Only provided fields are updated."""
        skill = storage.load_skill(skill_id)
        if not skill:
            return {"error": f"Skill {skill_id} not found"}

        # Track if we need to delete old file (name changed means new filename)
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

        skill.updated_at = datetime.now()

        # Delete old file if name changed (new file will be created with new name)
        if name is not None and name != old_name and old_file_path:
            storage._delete_file(old_file_path)

        storage.save(skill)
        return {"skill_id": skill.skill_id, "updated": True}
