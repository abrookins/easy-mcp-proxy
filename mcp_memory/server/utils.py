"""Utility functions for MCP Memory server tools."""

from mcp.types import TextContent

from mcp_memory.models import Concept


def _text(text: str) -> TextContent:
    """Wrap text in TextContent for MCP response."""
    return TextContent(type="text", text=text)


def _derive_title_from_text(text: str, max_length: int = 60) -> str:
    """Derive a thread title from message text.

    Takes the first line or sentence, truncates to max_length at word boundary.
    """
    # Get first line
    first_line = text.split("\n")[0].strip()

    # If short enough, use as-is
    if len(first_line) <= max_length:
        return first_line

    # Truncate at word boundary
    truncated = first_line[:max_length].rsplit(" ", 1)[0]
    return truncated + "..." if truncated else first_line[:max_length] + "..."


def _format_concept(concept: Concept) -> str:
    """Format a concept as markdown."""
    lines = [
        f"# {concept.name}",
        f"**Path:** `{concept.full_path}`",
        f"**Concept ID:** `{concept.concept_id}`",
    ]
    if concept.parent_path:
        lines.append(f"**Parent:** `{concept.parent_path}`")
    if concept.project_id:
        lines.append(f"**Project:** `{concept.project_id}`")
    if concept.tags:
        lines.append(f"**Tags:** {', '.join(concept.tags)}")
    if concept.links:
        lines.append(f"**Links:** {', '.join(concept.links)}")
    lines.append(f"**Updated:** {concept.updated_at:%Y-%m-%d %H:%M}")
    if concept.text:
        lines.append(f"\n---\n\n{concept.text}")
    return "\n".join(lines)
