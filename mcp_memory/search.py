"""Vector search for MCP Memory using FAISS and sentence transformers."""

import json
from pathlib import Path

import numpy as np

from mcp_memory.models import MemoryConfig
from mcp_memory.storage import MemoryStorage


class MemorySearcher:
    """Vector search over memory objects using FAISS.

    Automatically detects when files have changed and rebuilds the index.
    """

    def __init__(
        self,
        storage: MemoryStorage,
        config: MemoryConfig | None = None,
        model=None,
    ):
        self.storage = storage
        self.config = config or storage.config
        self._model = model  # Allow pre-loaded model injection for testing
        self._index = None
        self._id_map: list[dict] = []  # Maps index position to object info
        self._index_path = Path(self.config.base_path) / self.config.index_path
        self._file_mtimes: dict[str, float] = {}  # Track file modification times
        self._indexed_files: set[str] = set()  # Track which files are indexed

    @property
    def model(self):
        """Lazy load the sentence transformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.embedding_model)
        return self._model

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for a text string."""
        return self.model.encode([text], convert_to_numpy=True)[0]

    def _get_embeddings(self, texts: list[str]) -> np.ndarray:
        """Get embeddings for multiple texts."""
        if not texts:
            return np.array([])
        return self.model.encode(texts, convert_to_numpy=True)

    def _get_content_files(self) -> list[Path]:
        """Get all content files that should be indexed."""
        files = []
        base = Path(self.config.base_path)

        # Concept files (recursive for hierarchy support)
        concepts_dir = base / self.config.concepts_dir
        if concepts_dir.exists():
            files.extend(concepts_dir.glob("**/*.md"))

        # Extra concept directories (also recursive)
        for extra_dir in self.config.extra_concept_dirs:
            extra_path = base / extra_dir
            if extra_path.exists():
                files.extend(extra_path.glob("**/*.md"))

        # Thread files
        threads_dir = base / self.config.threads_dir
        if threads_dir.exists():
            files.extend(threads_dir.glob("*.yaml"))

        # Artifact files
        artifacts_dir = base / self.config.artifacts_dir
        if artifacts_dir.exists():
            files.extend(artifacts_dir.glob("*.md"))

        # Skill files
        skills_dir = base / self.config.skills_dir
        if skills_dir.exists():
            files.extend(skills_dir.glob("*.md"))

        # Episode files
        episodes_dir = base / self.config.episodes_dir
        if episodes_dir.exists():
            files.extend(episodes_dir.glob("*.md"))

        return files

    def _get_current_mtimes(self) -> dict[str, float]:
        """Get modification times for all content files."""
        mtimes = {}
        for f in self._get_content_files():
            try:
                mtimes[str(f)] = f.stat().st_mtime
            except OSError:
                pass  # File may have been deleted
        return mtimes

    def _is_index_stale(self) -> bool:
        """Check if index needs rebuilding due to file changes."""
        current_mtimes = self._get_current_mtimes()
        current_files = set(current_mtimes.keys())
        indexed_files = self._indexed_files

        # Check for new or deleted files
        if current_files != indexed_files:
            return True

        # Check for modified files
        for path, mtime in current_mtimes.items():
            if self._file_mtimes.get(path) != mtime:
                return True

        return False

    def build_index(self) -> None:
        """Build or rebuild the FAISS index from all indexed content."""
        import faiss

        texts = []
        id_map = []

        # Track file modification times
        self._file_mtimes = self._get_current_mtimes()
        self._indexed_files = set(self._file_mtimes.keys())

        # Index concepts (including full path for hierarchy)
        for concept in self.storage.list_concepts():
            # Include full path in searchable text for better discovery
            full_path = concept.full_path
            text = f"{full_path}\n{concept.name}\n{concept.text}"
            texts.append(text)
            id_map.append(
                {
                    "type": "concept",
                    "id": concept.concept_id,
                    "name": concept.name,
                    "path": full_path,
                    "project_id": concept.project_id,
                }
            )

        # Index threads (by their messages)
        for thread in self.storage.list_threads():
            for i, msg in enumerate(thread.messages):
                texts.append(msg.text)
                id_map.append(
                    {
                        "type": "message",
                        "thread_id": thread.thread_id,
                        "message_index": i,
                        "project_id": thread.project_id,
                    }
                )

        # Index artifacts (include path and tags for better discovery)
        for artifact in self.storage.list_artifacts():
            parts = [artifact.name, artifact.description, artifact.content]
            if artifact.path:
                parts.insert(0, artifact.path)
            if artifact.tags:
                parts.append(" ".join(artifact.tags))
            text = "\n".join(parts)
            texts.append(text)
            id_map.append(
                {
                    "type": "artifact",
                    "id": artifact.artifact_id,
                    "name": artifact.name,
                    "path": artifact.path,
                    "project_id": artifact.project_id,
                }
            )

        # Index skills (include tags for better discovery)
        for skill in self.storage.list_skills():
            parts = [skill.name, skill.description, skill.instructions]
            if skill.tags:
                parts.append(" ".join(skill.tags))
            text = "\n".join(parts)
            texts.append(text)
            id_map.append(
                {
                    "type": "skill",
                    "id": skill.skill_id,
                    "name": skill.name,
                }
            )

        # Index episodes (include title, events, and tags)
        for episode in self.storage.list_episodes():
            parts = [episode.source_title or "", episode.events]
            if episode.tags:
                parts.append(" ".join(episode.tags))
            text = "\n".join(parts)
            texts.append(text)
            id_map.append(
                {
                    "type": "episode",
                    "id": episode.episode_id,
                    "source_thread_id": episode.source_thread_id,
                    "project_id": episode.project_id,
                }
            )

        if not texts:
            # Create empty index
            dim = 384  # Default dimension for all-MiniLM-L6-v2
            self._index = faiss.IndexFlatL2(dim)
            self._id_map = []
            self._save_index()
            return

        # Get embeddings
        embeddings = self._get_embeddings(texts)
        dim = embeddings.shape[1]

        # Create FAISS index
        self._index = faiss.IndexFlatL2(dim)
        self._index.add(embeddings.astype(np.float32))
        self._id_map = id_map

        # Save index
        self._save_index()

    def _save_index(self) -> None:
        """Save the FAISS index, ID map, and file mtimes to disk."""
        import faiss

        self._index_path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path / "index.faiss"))
        with open(self._index_path / "id_map.json", "w") as f:
            json.dump(self._id_map, f)
        with open(self._index_path / "mtimes.json", "w") as f:
            json.dump(
                {
                    "mtimes": self._file_mtimes,
                    "files": list(self._indexed_files),
                },
                f,
            )

    def _load_index(self) -> bool:
        """Load the FAISS index from disk. Returns True if successful."""
        import faiss

        index_file = self._index_path / "index.faiss"
        map_file = self._index_path / "id_map.json"
        mtimes_file = self._index_path / "mtimes.json"

        if not index_file.exists() or not map_file.exists():
            return False

        self._index = faiss.read_index(str(index_file))
        with open(map_file) as f:
            self._id_map = json.load(f)

        # Load mtimes if available
        if mtimes_file.exists():
            with open(mtimes_file) as f:
                data = json.load(f)
                self._file_mtimes = data.get("mtimes", {})
                self._indexed_files = set(data.get("files", []))

        return True

    def ensure_index(self) -> None:
        """Ensure index is loaded and up-to-date, rebuilding if stale."""
        if self._index is None:
            if not self._load_index():
                self.build_index()
                return

        # Check if index is stale and rebuild if needed
        if self._is_index_stale():
            self.build_index()

    def search_concepts(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
    ) -> list[dict]:
        """Search concepts by semantic similarity."""
        self.ensure_index()
        return self._search(query, "concept", limit, project_id=project_id)

    def search_messages(
        self,
        query: str,
        limit: int = 10,
        thread_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict]:
        """Search messages by semantic similarity."""
        self.ensure_index()
        return self._search(
            query, "message", limit, thread_id=thread_id, project_id=project_id
        )

    def search_threads(self, query: str, limit: int = 10) -> list[dict]:
        """Search threads by their message content."""
        results = self.search_messages(query, limit=limit * 3)
        # Deduplicate by thread_id
        seen = set()
        threads = []
        for r in results:
            tid = r.get("thread_id")
            if tid and tid not in seen:
                seen.add(tid)
                threads.append({"thread_id": tid, "score": r["score"]})
                if len(threads) >= limit:
                    break
        return threads

    def search_artifacts(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
    ) -> list[dict]:
        """Search artifacts by semantic similarity."""
        self.ensure_index()
        return self._search(query, "artifact", limit, project_id=project_id)

    def search_skills(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search skills by semantic similarity."""
        self.ensure_index()
        return self._search(query, "skill", limit)

    def search_episodes(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
    ) -> list[dict]:
        """Search episodes by semantic similarity."""
        self.ensure_index()
        return self._search(query, "episode", limit, project_id=project_id)

    def _search(
        self,
        query: str,
        item_type: str,
        limit: int,
        thread_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict]:
        """Internal search method."""
        if self._index is None or self._index.ntotal == 0:
            return []

        # Get query embedding
        query_embedding = self._get_embedding(query).astype(np.float32).reshape(1, -1)

        # Search more than needed to allow for filtering
        k = min(limit * 5, self._index.ntotal)
        distances, indices = self._index.search(query_embedding, k)

        results = []
        seen_ids = set()  # Track seen IDs to avoid duplicates

        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._id_map):
                continue

            item = self._id_map[idx]
            if item["type"] != item_type:
                continue

            # Apply filters
            if thread_id and item.get("thread_id") != thread_id:
                continue
            if project_id and item.get("project_id") != project_id:
                continue

            # Deduplicate by ID or thread_id+message_index (for messages)
            if item_type in ("concept", "artifact", "skill", "episode"):
                item_id = item.get("id")
            else:
                # For messages, use composite key
                item_id = f"{item.get('thread_id')}:{item.get('message_index')}"

            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            result = {**item, "score": float(dist)}
            results.append(result)

            if len(results) >= limit:
                break

        return results

    def add_to_index(self, item_type: str, text: str, metadata: dict) -> None:
        """Add a single item to the index.

        Skips if the item is already indexed (to avoid duplicates when
        ensure_index triggers a rebuild from files).
        """
        self.ensure_index()

        # Check if item is already in the index
        item_id = metadata.get("id") or metadata.get("thread_id")
        for existing in self._id_map:
            if existing.get("type") == item_type:
                existing_id = existing.get("id") or existing.get("thread_id")
                if existing_id == item_id:
                    # Already indexed (likely by ensure_index/build_index)
                    return

        embedding = self._get_embedding(text).astype(np.float32).reshape(1, -1)
        self._index.add(embedding)
        self._id_map.append({"type": item_type, **metadata})
        self._save_index()
