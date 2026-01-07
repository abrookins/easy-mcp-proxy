"""Episode storage mixin."""

from typing import TYPE_CHECKING

from mcp_memory.models import Episode

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class EpisodeStorageMixin:
    """Mixin for episode-related storage operations."""

    def load_episode(self: "BaseStorage", episode_id: str) -> Episode | None:
        """Load an episode by ID."""
        dir_path = self._get_dir("Episode")
        file_path = dir_path / f"{episode_id}.md"
        if not file_path.exists():
            return None
        return self._load_markdown_file(file_path, Episode, "events")

    def list_episodes(
        self: "BaseStorage",
        project_id: str | None = None,
        source_thread_id: str | None = None,
    ) -> list[Episode]:
        """List episodes, optionally filtered by project or source thread."""
        dir_path = self._get_dir("Episode")
        if not dir_path.exists():
            return []
        episodes = []
        for file_path in dir_path.glob("*.md"):
            obj = self._load_markdown_file(file_path, Episode, "events")
            if obj:  # pragma: no branch
                if project_id and obj.project_id != project_id:
                    continue
                if source_thread_id and obj.source_thread_id != source_thread_id:
                    continue
                episodes.append(obj)
        return episodes
