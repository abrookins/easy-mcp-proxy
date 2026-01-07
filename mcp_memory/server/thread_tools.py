"""Thread tools for MCP Memory server."""

# ruff: noqa: E501

from datetime import datetime

from fastmcp import FastMCP
from mcp.types import TextContent

from mcp_memory.models import Message, Thread
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .utils import _derive_title_from_text, _text


def register_thread_tools(
    mcp: FastMCP, storage: MemoryStorage, searcher: MemorySearcher
) -> None:
    """Register all thread-related tools with the MCP server."""

    @mcp.tool()
    def create_thread(
        project_id: str | None = None,
        thread_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Create a new conversation thread for persisting messages across sessions. Call this at the start of conversations you want to remember. Title is auto-derived from the first message if not provided."""
        thread = Thread(project_id=project_id, title=title)
        if thread_id:
            thread.thread_id = thread_id
        storage.save(thread)
        return {"thread_id": thread.thread_id, "title": thread.title, "created": True}

    @mcp.tool()
    def read_thread(
        thread_id: str,
        messages_from: str | None = None,
    ) -> TextContent:
        """Retrieve a thread and its messages. Use when resuming a conversation to restore context. Pass messages_from as ISO timestamp to get only messages added since your last sync."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return _text(f"Thread {thread_id} not found")

        messages = thread.messages
        if messages_from:
            from_dt = datetime.fromisoformat(messages_from)
            messages = [m for m in messages if m.timestamp >= from_dt]

        lines = [
            f"# {thread.title or 'Untitled'}",
            f"**Thread ID:** `{thread.thread_id}`",
        ]
        if thread.project_id:
            lines.append(f"**Project:** `{thread.project_id}`")
        if thread.processing_status != "pending":
            lines.append(f"**Status:** {thread.processing_status}")
        if thread.episode_id:
            lines.append(f"**Episode:** `{thread.episode_id}`")
        if thread.summary:
            lines.append(f"\n**Summary:** {thread.summary}")
        lines.append(f"\n## Messages ({len(messages)})\n")
        for m in messages:
            lines.append(f"**{m.role}** ({m.timestamp:%Y-%m-%d %H:%M}):\n{m.text}\n")
        return _text("\n".join(lines))

    @mcp.tool()
    def add_messages(
        thread_id: str,
        messages: list[dict],
    ) -> dict:
        """Append messages to an existing thread. Call frequently during conversations to persist context—don't wait until the end. Each message needs 'role' (user/assistant) and 'text' fields; 'timestamp' is optional (defaults to now)."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        for msg_data in messages:
            ts_str = msg_data.get("timestamp", datetime.now().isoformat())
            msg = Message(
                role=msg_data["role"],
                text=msg_data["text"],
                timestamp=datetime.fromisoformat(ts_str),
            )
            thread.messages.append(msg)
            # Add to search index
            searcher.add_to_index(
                "message",
                msg.text,
                {
                    "thread_id": thread_id,
                    "message_index": len(thread.messages) - 1,
                    "project_id": thread.project_id,
                },
            )

        # Auto-derive title from first message if not already set
        if not thread.title and thread.messages:
            thread.title = _derive_title_from_text(thread.messages[0].text)

        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "message_count": len(thread.messages)}

    @mcp.tool()
    def search_messages(
        query: str,
        thread_id: str | None = None,
        project_id: str | None = None,
        limit: int = 10,
    ) -> TextContent:
        """Find past conversation content using semantic search. Returns thread IDs and message indices—use read_thread() to get full context. Filter by thread_id or project_id to narrow results."""
        results = searcher.search_messages(
            query, limit=limit, thread_id=thread_id, project_id=project_id
        )
        if not results:
            return _text(f"No messages found for query: {query}")
        lines = [f"# Message Search Results ({len(results)})\n"]
        for r in results:
            lines.append(
                f"- Thread `{r['thread_id']}` msg#{r['message_index']} "
                f"(score: {r['score']:.2f})"
            )
        return _text("\n".join(lines))

    @mcp.tool()
    def find_threads(
        query: str | None = None, project_id: str | None = None, limit: int = 50
    ) -> TextContent:
        """Find or list threads. With query: semantic search. Without: list all.

        Args:
            query: Semantic search query. If None, lists all threads.
            project_id: Filter by project (list mode only).
            limit: Max results (default 50 for list, 10 for search).

        Examples:
            find_threads()  # List all threads
            find_threads(project_id="proj_123")  # List threads in project
            find_threads(query="authentication bug")  # Search threads
        """
        if query:
            # Semantic search mode
            search_limit = min(limit, 10)  # Default search limit is smaller
            results = searcher.search_threads(query, limit=search_limit)
            if not results:
                return _text(f"No threads found for query: {query}")
            lines = [f"# Thread Search Results ({len(results)})\n"]
            for r in results:
                title = r.get("title", "Untitled")
                lines.append(
                    f"- `{r['thread_id']}` **{title}** (score: {r['score']:.2f})"
                )
            return _text("\n".join(lines))
        else:
            # List mode
            threads = storage.list_threads(project_id=project_id)
            threads.sort(key=lambda t: t.updated_at, reverse=True)
            threads = threads[:limit]
            if not threads:
                return _text("No threads found")
            lines = [f"# Threads ({len(threads)})\n"]
            for t in threads:
                project_info = f" [project: `{t.project_id}`]" if t.project_id else ""
                summary_mark = " 📝" if t.summary else ""
                lines.append(
                    f"- `{t.thread_id}` **{t.title or 'Untitled'}**{project_info}\n"
                    f"  {len(t.messages)} msgs, updated {t.updated_at:%Y-%m-%d}{summary_mark}"
                )
            return _text("\n".join(lines))

    @mcp.tool()
    def compact_thread(thread_id: str, summary: str) -> dict:
        """Replace a thread's messages with a summary to reduce storage. Use for long threads where individual messages are no longer needed. The summary becomes the thread's new context—messages are deleted permanently."""
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        thread.summary = summary
        thread.messages = []  # Clear messages after summarizing
        thread.updated_at = datetime.now()
        storage.save(thread)
        return {"thread_id": thread_id, "compacted": True}

    @mcp.tool()
    def delete_thread(thread_id: str) -> dict:
        """Delete a thread by its ID.

        This permanently removes the thread and all its messages from storage
        and the search index. Use with caution—this action cannot be undone.

        Args:
            thread_id: The ID of the thread to delete.

        Returns:
            A dict with deleted=True on success, or error message on failure.
        """
        thread = storage.load_thread(thread_id)
        if not thread:
            return {"error": f"Thread {thread_id} not found"}

        # Delete the thread file
        file_path = storage._get_dir("Thread") / f"{thread_id}.yaml"
        if file_path.exists():
            file_path.unlink()

        # Rebuild index to remove the thread and messages from search
        searcher.build_index()

        return {
            "thread_id": thread_id,
            "title": thread.title,
            "deleted": True,
        }
