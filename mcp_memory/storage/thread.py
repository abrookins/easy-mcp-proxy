"""Thread storage mixin."""

from typing import TYPE_CHECKING

import yaml

from mcp_memory.models import Thread

if TYPE_CHECKING:
    from mcp_memory.storage.base import BaseStorage


class ThreadStorageMixin:
    """Mixin for thread-related storage operations."""

    def load_thread(self: "BaseStorage", thread_id: str) -> Thread | None:
        """Load a thread by ID."""
        dir_path = self._get_dir("Thread")
        file_path = dir_path / f"{thread_id}.yaml"
        if not file_path.exists():
            return None
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return Thread.model_validate(data)

    def list_threads(
        self: "BaseStorage", project_id: str | None = None
    ) -> list[Thread]:
        """List all threads, optionally filtered by project."""
        dir_path = self._get_dir("Thread")
        if not dir_path.exists():
            return []
        threads = []
        for file_path in dir_path.glob("*.yaml"):
            content = file_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            thread = Thread.model_validate(data)
            if project_id is None or thread.project_id == project_id:
                threads.append(thread)
        return threads

