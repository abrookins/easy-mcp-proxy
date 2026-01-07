"""Episode tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Episode
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _text


def _format_episode(episode: Episode) -> str:
    """Format an episode for display."""
    lines = [
        f"# {episode.source_title or 'Untitled Episode'}",
        f"**Episode ID:** `{episode.episode_id}`",
        f"**Source Thread:** `{episode.source_thread_id}`",
        f"**Time:** {episode.started_at:%Y-%m-%d %H:%M} → {episode.ended_at:%H:%M}",
    ]
    if episode.timezone:
        lines.append(f"**Timezone:** {episode.timezone}")
    if episode.platform:
        lines.append(f"**Platform:** {episode.platform}")
    if episode.project_id:
        lines.append(f"**Project:** `{episode.project_id}`")
    if episode.tags:
        lines.append(f"**Tags:** {', '.join(episode.tags)}")
    if episode.concept_ids:
        lines.append(
            f"**Linked Concepts:** {', '.join(f'`{c}`' for c in episode.concept_ids)}"
        )

    # Qualities
    if episode.input_modalities:
        lines.append(f"**Input:** {', '.join(episode.input_modalities)}")
    if episode.output_modalities:
        lines.append(f"**Output:** {', '.join(episode.output_modalities)}")
    if episode.voice_mode:
        lines.append("**Voice Mode:** Yes")
    if episode.client:
        lines.append(f"**Client:** {episode.client}")
    if episode.model:
        lines.append(f"**Model:** {episode.model}")

    lines.append(f"\n## Events\n\n{episode.events}")
    return "\n".join(lines)


def register_episode_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all episode-related tools with the MCP server."""

    @mcp.tool()
    def upsert_episode(
        episode_id: str | None = None,
        source_thread_id: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        events: str | None = None,
        platform: str | None = None,
        source_title: str | None = None,
        timezone: str | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        concept_ids: list[str] | None = None,
        input_modalities: list[str] | None = None,
        output_modalities: list[str] | None = None,
        voice_mode: bool | None = None,
        client: str | None = None,
        model: str | None = None,
        qualities: dict[str, Any] | None = None,
    ) -> dict:
        """Create or update an episode (objective record of experience). If episode_id is provided, updates the existing episode. Otherwise creates a new episode.

        Args:
            episode_id: If provided, update this episode; otherwise create new
            source_thread_id: Thread this episode was derived from (required for create)
            started_at: When the experience started (ISO format, required for create)
            ended_at: When the experience ended (ISO format, required for create)
            events: Markdown narrated events (the objective record)
            platform: Source platform ("chatgpt", "claude", etc.)
            source_title: Title from the source
            timezone: Timezone of the experience
            project_id: Associate with a project
            tags: Tags for categorization
            concept_ids: Link to concepts derived from this episode
            input_modalities: Input types ["text", "voice", "image"]
            output_modalities: Output types
            voice_mode: Whether voice mode was used
            client: Client app used ("ios_app", "web", etc.)
            model: Model used if known
            qualities: Additional key-value metadata
        """
        if episode_id:
            # Update existing episode
            episode = storage.load_episode(episode_id)
            if not episode:
                return {"error": f"Episode {episode_id} not found"}

            if source_thread_id is not None:
                episode.source_thread_id = source_thread_id
            if started_at is not None:
                episode.started_at = datetime.fromisoformat(started_at)
            if ended_at is not None:
                episode.ended_at = datetime.fromisoformat(ended_at)
            if events is not None:
                episode.events = events
            if platform is not None:
                episode.platform = platform
            if source_title is not None:
                episode.source_title = source_title
            if timezone is not None:
                episode.timezone = timezone
            if project_id is not None:
                episode.project_id = project_id
            if tags is not None:
                episode.tags = tags
            if concept_ids is not None:
                episode.concept_ids = concept_ids
            if input_modalities is not None:
                episode.input_modalities = input_modalities
            if output_modalities is not None:
                episode.output_modalities = output_modalities
            if voice_mode is not None:
                episode.voice_mode = voice_mode
            if client is not None:
                episode.client = client
            if model is not None:
                episode.model = model
            if qualities is not None:
                episode.qualities = qualities

            episode.updated_at = datetime.now()
            storage.save(episode)
            searcher.build_index()
            return {"episode_id": episode_id, "updated": True}
        else:
            # Create - validate required fields
            if not source_thread_id:
                return {"error": "source_thread_id required for new episode"}
            if not started_at:
                return {"error": "started_at required for new episode"}
            if not ended_at:
                return {"error": "ended_at required for new episode"}

            episode = Episode(
                source_thread_id=source_thread_id,
                started_at=datetime.fromisoformat(started_at),
                ended_at=datetime.fromisoformat(ended_at),
                events=events or "",
                platform=platform,
                source_title=source_title,
                timezone=timezone,
                project_id=project_id,
                tags=tags or [],
                concept_ids=concept_ids or [],
                input_modalities=input_modalities or [],
                output_modalities=output_modalities or [],
                voice_mode=voice_mode or False,
                client=client,
                model=model,
                qualities=qualities or {},
            )
            storage.save(episode)

            # Update source thread to link back and mark processed
            thread = storage.load_thread(source_thread_id)
            if thread:
                thread.episode_id = episode.episode_id
                thread.processing_status = "completed"
                thread.updated_at = datetime.now()
                storage.save(thread)

            # Add to search index
            searcher.add_to_index(
                "episode",
                f"{source_title or ''}\n{events or ''}",
                {
                    "id": episode.episode_id,
                    "source_thread_id": source_thread_id,
                    "project_id": project_id,
                },
            )
            return {"episode_id": episode.episode_id, "created": True}

    @mcp.tool()
    def get_episode(episode_id: str) -> TextContent:
        """Retrieve an episode by ID."""
        episode = storage.load_episode(episode_id)
        if not episode:
            return _text(f"Episode {episode_id} not found")
        return _text(_format_episode(episode))

    @mcp.tool()
    def find_episodes(
        query: str | None = None,
        project_id: str | None = None,
        source_thread_id: str | None = None,
        limit: int = 10,
    ) -> TextContent:
        """Find or list episodes. With query: semantic search. Without: list all.

        Args:
            query: Semantic search query. If None, lists all episodes.
            project_id: Filter by project.
            source_thread_id: Filter by source thread.
            limit: Max results (default 10).
        """
        if query:
            # Semantic search
            results = searcher.search_episodes(
                query, limit=limit, project_id=project_id
            )
            if not results:
                return _text(f"No episodes found for query: {query}")
            lines = [f"# Episode Search Results ({len(results)})\n"]
            for r in results:
                lines.append(
                    f"- `{r['id']}` (thread: `{r.get('source_thread_id', '?')}`, "
                    f"score: {r['score']:.2f})"
                )
            return _text("\n".join(lines))
        else:
            # List mode
            episodes = storage.list_episodes(
                project_id=project_id, source_thread_id=source_thread_id
            )
            episodes.sort(key=lambda e: e.started_at, reverse=True)
            episodes = episodes[:limit]
            if not episodes:
                return _text("No episodes found")
            lines = [f"# Episodes ({len(episodes)})\n"]
            for e in episodes:
                title = e.source_title or "Untitled"
                project_info = f" [project: `{e.project_id}`]" if e.project_id else ""
                concept_count = (
                    f" ({len(e.concept_ids)} concepts)" if e.concept_ids else ""
                )
                lines.append(
                    f"- `{e.episode_id}` **{title}**{project_info}{concept_count}\n"
                    f"  {e.started_at:%Y-%m-%d %H:%M} ({e.platform or 'unknown'})"
                )
            return _text("\n".join(lines))

    @mcp.tool()
    def link_episode_to_concept(episode_id: str, concept_id: str) -> dict:
        """Create bidirectional link between an episode and a concept.

        Adds concept_id to the episode's concept_ids list, and adds episode_id
        to the concept's episode_ids list.
        """
        episode = storage.load_episode(episode_id)
        if not episode:
            return {"error": f"Episode {episode_id} not found"}

        concept = storage.load_concept(concept_id)
        if not concept:
            return {"error": f"Concept {concept_id} not found"}

        # Add links if not already present
        updated = False
        if concept_id not in episode.concept_ids:
            episode.concept_ids.append(concept_id)
            episode.updated_at = datetime.now()
            storage.save(episode)
            updated = True

        if episode_id not in concept.episode_ids:
            concept.episode_ids.append(episode_id)
            concept.updated_at = datetime.now()
            storage.save(concept)
            updated = True

        return {
            "episode_id": episode_id,
            "concept_id": concept_id,
            "linked": updated,
            "already_linked": not updated,
        }

    @mcp.tool()
    def get_pending_threads() -> TextContent:
        """List threads that haven't been processed into episodes yet.

        Use this to discover which threads need conceptualization work.
        """
        threads = storage.list_threads()
        pending = [t for t in threads if t.processing_status == "pending"]
        pending.sort(key=lambda t: t.updated_at, reverse=True)

        if not pending:
            return _text("No pending threads. All threads have been processed.")

        lines = [f"# Pending Threads ({len(pending)})\n"]
        for t in pending:
            project_info = f" [project: `{t.project_id}`]" if t.project_id else ""
            lines.append(
                f"- `{t.thread_id}` **{t.title or 'Untitled'}**{project_info}\n"
                f"  {len(t.messages)} msgs, updated {t.updated_at:%Y-%m-%d}"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def mark_thread_status(
        thread_id: str,
        status: str,
    ) -> dict:
        """Update a thread's processing status.

        Args:
            thread_id: Thread to update
            status: New status ("pending", "processing", or "completed")
        """
        if status not in ("pending", "processing", "completed"):
            return {
                "error": f"Invalid status: {status}. Use pending/processing/completed"
            }

        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        thread.processing_status = status  # type: ignore[assignment]
        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "status": status, "updated": True}

    @mcp.tool()
    def delete_episode(episode_id: str) -> dict:
        """Delete an episode by its ID.

        This permanently removes the episode from storage and the search index.
        Use with caution—this action cannot be undone.

        Args:
            episode_id: The ID of the episode to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        episode = storage.load_episode(episode_id)
        if not episode:
            return {"error": f"Episode {episode_id} not found"}

        # Find and delete the file
        file_path = storage._find_file_by_id("Episode", "episode_id", episode_id)
        if file_path:
            storage._delete_file(file_path)

        # Rebuild index to remove the episode from search
        searcher.build_index()

        return {
            "episode_id": episode_id,
            "source_title": episode.source_title,
            "deleted": True,
        }
