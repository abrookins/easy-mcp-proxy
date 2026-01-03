"""Tests for mcp_memory storage layer."""

import pytest
from pathlib import Path

from mcp_memory.models import (
    Concept,
    MemoryConfig,
    Message,
    Project,
    Reflection,
    Skill,
    Thread,
)
from mcp_memory.storage import (
    MemoryStorage,
    format_frontmatter,
    parse_frontmatter,
)


class TestFrontmatterParsing:
    """Tests for YAML frontmatter parsing."""

    def test_parse_frontmatter_basic(self):
        """Test parsing basic frontmatter."""
        content = """---
name: Test
value: 123
---

Body content here."""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["name"] == "Test"
        assert frontmatter["value"] == 123
        assert body == "Body content here."

    def test_parse_frontmatter_no_body(self):
        """Test parsing frontmatter without body."""
        content = """---
name: Test
---
"""
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter["name"] == "Test"
        assert body == ""

    def test_parse_frontmatter_no_frontmatter(self):
        """Test parsing content without frontmatter."""
        content = "Just plain text"
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter == {}
        assert body == "Just plain text"

    def test_format_frontmatter_with_body(self):
        """Test formatting frontmatter with body."""
        result = format_frontmatter({"name": "Test"}, "Body text")
        assert result.startswith("---\n")
        assert "name: Test" in result
        assert result.endswith("Body text")

    def test_format_frontmatter_without_body(self):
        """Test formatting frontmatter without body."""
        result = format_frontmatter({"name": "Test"})
        assert result.startswith("---\n")
        assert "name: Test" in result
        assert result.endswith("---\n")


class TestMemoryStorage:
    """Tests for MemoryStorage class."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with temp directory."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)

    def test_save_and_load_thread(self, storage):
        """Test saving and loading a thread."""
        thread = Thread(project_id="p_test")
        thread.messages.append(Message(role="user", text="Hello"))
        thread.messages.append(Message(role="assistant", text="Hi there"))

        path = storage.save(thread)
        assert path.exists()
        assert path.suffix == ".yaml"

        loaded = storage.load_thread(thread.thread_id)
        assert loaded is not None
        assert loaded.thread_id == thread.thread_id
        assert loaded.project_id == "p_test"
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == "user"
        assert loaded.messages[0].text == "Hello"

    def test_save_and_load_concept(self, storage):
        """Test saving and loading a concept."""
        concept = Concept(
            name="Lane Harker",
            text="A character description.\n\nWith multiple paragraphs.",
            tags=["character"],
        )

        path = storage.save(concept)
        assert path.exists()
        assert path.suffix == ".md"
        assert "Lane Harker" in path.name

        loaded = storage.load_concept_by_name("Lane Harker")
        assert loaded is not None
        assert loaded.name == "Lane Harker"
        assert "character description" in loaded.text
        assert "character" in loaded.tags

    def test_save_and_load_project(self, storage):
        """Test saving and loading a project."""
        project = Project(
            name="Island Story",
            description="A novel about an island",
            instructions="Write in third person\n\nUse vivid descriptions",
        )

        storage.save(project)
        loaded = storage.load_project_by_name("Island Story")

        assert loaded is not None
        assert loaded.name == "Island Story"
        assert loaded.description == "A novel about an island"
        assert "third person" in loaded.instructions

    def test_save_and_load_skill(self, storage):
        """Test saving and loading a skill."""
        skill = Skill(
            name="Code Review",
            description="How to review code",
            instructions="1. Check for bugs\n2. Check for style",
        )

        storage.save(skill)
        loaded = storage.load_skill(skill.skill_id)

        assert loaded is not None
        assert loaded.name == "Code Review"
        assert "Check for bugs" in loaded.instructions

    def test_save_and_load_reflection(self, storage):
        """Test saving and loading a reflection."""
        reflection = Reflection(
            text="I learned something important today.",
            project_id="p_123",
            skill_id="s_456",
        )

        storage.save(reflection)
        loaded = storage.load_reflection(reflection.reflection_id)

        assert loaded is not None
        assert "learned something" in loaded.text
        assert loaded.project_id == "p_123"
        assert loaded.skill_id == "s_456"

    def test_list_threads(self, storage):
        """Test listing threads."""
        t1 = Thread(project_id="p_1")
        t2 = Thread(project_id="p_1")
        t3 = Thread(project_id="p_2")

        storage.save(t1)
        storage.save(t2)
        storage.save(t3)

        all_threads = storage.list_threads()
        assert len(all_threads) == 3

        project_threads = storage.list_threads(project_id="p_1")
        assert len(project_threads) == 2


class TestIndexAutoUpdate:
    """Tests for automatic index updates when files change."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with temp directory."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)

    def test_search_finds_updated_content(self, tmp_path):
        """When a concept is updated, search should find the new content."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Create initial concept
        concept = Concept(name="Lane Harker", text="A journalist in New York")
        storage.save(concept)

        # Build initial index
        searcher.build_index()

        # Verify initial search works
        results = searcher.search_concepts("journalist New York")
        assert len(results) > 0
        assert results[0]["name"] == "Lane Harker"

        # Update the concept with completely different content
        concept.text = "A marine biologist studying dolphins in Hawaii"
        storage.save(concept)

        # Search for NEW content - should find it after auto-update
        results = searcher.search_concepts("marine biologist dolphins Hawaii")
        assert len(results) > 0, "Index should auto-update when files change"
        assert results[0]["name"] == "Lane Harker"

        # Search for OLD content - should NOT find it (or rank lower)
        old_results = searcher.search_concepts("journalist New York")
        if old_results:
            # If found, should have worse score than new content search
            new_results = searcher.search_concepts("marine biologist dolphins")
            assert new_results[0]["score"] < old_results[0]["score"]

    def test_search_finds_new_files(self, tmp_path):
        """When new files are added externally, search should find them."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Build empty index
        searcher.build_index()

        # Add a file externally (simulating Obsidian edit)
        concepts_dir = tmp_path / "Concepts"
        concepts_dir.mkdir(exist_ok=True)
        (concepts_dir / "New Character.md").write_text(
            "---\ntags: [character]\n---\nA wizard who lives in a tower"
        )

        # Search should find the new file
        results = searcher.search_concepts("wizard tower")
        assert len(results) > 0, "Index should detect and index new files"
        assert results[0]["name"] == "New Character"

    def test_search_handles_deleted_files(self, tmp_path):
        """When files are deleted, search should not return them."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Create and index a concept
        concept = Concept(name="To Delete", text="This will be removed")
        storage.save(concept)
        searcher.build_index()

        # Delete the file externally
        concepts_dir = tmp_path / "Concepts"
        (concepts_dir / "To Delete.md").unlink()

        # Search should not return the deleted file
        results = searcher.search_concepts("This will be removed")
        # Should either return empty or the result should be marked as invalid
        for r in results:
            assert r.get("name") != "To Delete", "Deleted files should not appear"


class TestObsidianCompatibility:
    """Tests for Obsidian vault compatibility."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with temp directory."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)

    def test_load_obsidian_style_file(self, storage, tmp_path):
        """Test loading a file with Obsidian-style frontmatter."""
        concepts_dir = tmp_path / "Concepts"
        concepts_dir.mkdir()

        # Obsidian file: no concept_id, no name field, has aliases
        obsidian_content = """---
aliases: [Lane, LH]
tags: [character, protagonist]
created: 2024-06-15
---

# Lane Harker

Lane is the main character of the story.
"""
        (concepts_dir / "Lane Harker.md").write_text(obsidian_content)

        # Load by exact name
        concept = storage.load_concept_by_name("Lane Harker")
        assert concept is not None
        assert concept.name == "Lane Harker"
        assert concept.concept_id == "Lane Harker"  # Derived from filename
        assert concept.aliases == ["Lane", "LH"]
        assert "character" in concept.tags

    def test_load_by_alias(self, storage, tmp_path):
        """Test loading concept by Obsidian alias."""
        concepts_dir = tmp_path / "Concepts"
        concepts_dir.mkdir()

        content = """---
aliases: [Johnny, JD]
---

John Doe is a character.
"""
        (concepts_dir / "John Doe.md").write_text(content)

        # Load by alias
        concept = storage.load_concept_by_name("Johnny")
        assert concept is not None
        assert concept.name == "John Doe"

    def test_extra_concept_dirs(self, tmp_path):
        """Test scanning extra directories for concepts."""
        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["People", "Characters"],
        )
        storage = MemoryStorage(config)

        # Create extra directories
        (tmp_path / "People").mkdir()
        (tmp_path / "Characters").mkdir()

        # Add files to extra directories
        (tmp_path / "People" / "Alice.md").write_text("---\ntags: [person]\n---\nAlice")
        (tmp_path / "Characters" / "Bob.md").write_text("---\ntags: [char]\n---\nBob")

        concepts = storage.list_concepts()
        names = [c.name for c in concepts]
        assert "Alice" in names
        assert "Bob" in names


class TestSearchDeduplication:
    """Tests for ensuring search results don't contain duplicates."""

    def test_search_concepts_returns_no_duplicates(self, tmp_path):
        """Search should never return the same concept twice."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Create a single concept
        concept = Concept(
            name="Ahsoka Tano",
            text="A Togruta former Jedi who trained under Anakin Skywalker",
            tags=["character", "jedi"],
        )
        storage.save(concept)

        # Build index and search
        searcher.build_index()
        results = searcher.search_concepts("Jedi trained by Anakin")

        # Should find exactly one result, not duplicates
        assert len(results) == 1, f"Expected 1 result, got {len(results)}: {results}"
        assert results[0]["name"] == "Ahsoka Tano"

    def test_search_after_create_no_duplicates(self, tmp_path):
        """Creating a concept and immediately searching should not produce duplicates."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Create concept (this may trigger add_to_index)
        concept = Concept(
            name="Obi-Wan Kenobi",
            text="A Jedi Master who trained Anakin Skywalker",
        )
        storage.save(concept)

        # Add to index explicitly (simulating what server does)
        searcher.add_to_index(
            "concept",
            f"{concept.name}\n{concept.text}",
            {"id": concept.concept_id, "name": concept.name, "project_id": None},
        )

        # The index itself should not contain duplicates
        concept_ids_in_index = [
            item["id"] for item in searcher._id_map if item["type"] == "concept"
        ]
        assert len(concept_ids_in_index) == len(set(concept_ids_in_index)), (
            f"Index contains duplicate entries: {concept_ids_in_index}"
        )

    def test_multiple_searches_no_duplicates(self, tmp_path):
        """Multiple searches should not accumulate duplicates in the index."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config)

        # Create concepts
        for name in ["Luke Skywalker", "Leia Organa", "Han Solo"]:
            concept = Concept(name=name, text=f"{name} is a hero of the Rebellion")
            storage.save(concept)

        # Search multiple times
        for _ in range(3):
            results = searcher.search_concepts("hero of the Rebellion")
            concept_ids = [r["id"] for r in results]
            unique_ids = set(concept_ids)
            assert len(concept_ids) == len(unique_ids), (
                f"Duplicate results after repeated search: {concept_ids}"
            )

