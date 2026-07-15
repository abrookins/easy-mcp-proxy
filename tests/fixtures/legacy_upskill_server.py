"""Minimal pre-registry Upskill-compatible MCP fixture."""

from fastmcp import FastMCP

server = FastMCP("legacy-upskill")


@server.tool
def find_skills(query: str = "") -> dict:
    """Return the legacy fixture skills."""
    skills = [{"name": "legacy-skill", "description": "Legacy fixture"}]
    if query:
        skills = [item for item in skills if query.lower() in item["name"]]
    return {"skills": skills}


@server.tool
def promote_skill_draft(draft_id: str, to_source: str, dry_run: bool = True) -> dict:
    """Return the old promotion response shape."""
    return {
        "draft_id": draft_id,
        "destination": to_source,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    server.run(transport="stdio")
