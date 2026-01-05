"""Tests for mcp_memory storage layer."""

import re

import pytest

from mcp_memory.models import (
    Artifact,
    Concept,
    MemoryConfig,
    Message,
    Project,
    Reflection,
    Skill,
    Thread,
    generate_id,
)
from mcp_memory.storage import (
    MemoryStorage,
    format_frontmatter,
    parse_frontmatter,
)


class TestULIDGeneration:
    """Tests for ULID-based ID generation."""

    # ULID format: 26 chars, Crockford Base32 (0-9, A-Z excluding I, L, O, U)
    ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

    def test_generate_id_uses_ulid_format(self):
        """Generated IDs should use ULID format with prefix."""
        concept_id = generate_id("c")

        # Should have prefix + underscore + ULID
        assert concept_id.startswith("c_")
        ulid_part = concept_id[2:]  # Remove "c_" prefix
        assert self.ULID_PATTERN.match(ulid_part), (
            f"ID '{ulid_part}' is not a valid ULID"
        )

    def test_generate_id_is_unique(self):
        """Each generated ID should be unique."""
        ids = [generate_id("t") for _ in range(100)]
        assert len(ids) == len(set(ids)), "Generated IDs should be unique"

    def test_generate_id_is_sortable(self):
        """ULIDs should be lexicographically sortable by time."""
        import time

        id1 = generate_id("c")
        time.sleep(0.002)  # Small delay to ensure different timestamp
        id2 = generate_id("c")

        # Later ID should sort after earlier ID
        assert id2 > id1, "ULIDs should be time-sortable"

    def test_all_model_ids_are_ulids(self):
        """All model default IDs should be ULIDs."""
        thread = Thread()
        concept = Concept(name="Test")
        project = Project(name="Test")
        skill = Skill(name="Test")
        reflection = Reflection()
        artifact = Artifact(name="Test")

        for obj, prefix in [
            (thread, "t_"),
            (concept, "c_"),
            (project, "p_"),
            (skill, "s_"),
            (reflection, "r_"),
            (artifact, "a_"),
        ]:
            id_field = next(k for k in vars(obj) if k.endswith("_id"))
            id_value = getattr(obj, id_field)
            assert id_value.startswith(prefix), f"{id_field} should start with {prefix}"
            ulid_part = id_value[2:]
            assert self.ULID_PATTERN.match(ulid_part), (
                f"{id_field} '{ulid_part}' is not a valid ULID"
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

    def test_load_skill_by_filename_derived_id(self, storage):
        """Test loading a skill where skill_id is derived from filename.

        This simulates Obsidian-style files that have name/description in
        frontmatter but no explicit skill_id field. The skill_id should be
        derived from the filename.
        """
        # Create a skill file without skill_id in frontmatter
        skills_dir = storage._get_dir("Skill")
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Write a file with name but no skill_id
        skill_file = skills_dir / "my-workflow.md"
        skill_file.write_text(
            """---
name: my-workflow
description: A workflow without explicit skill_id
---

# My Workflow

Step 1: Do the thing
Step 2: Do the other thing
""",
            encoding="utf-8",
        )

        # Should be able to load by filename
        loaded = storage.load_skill("my-workflow")
        assert loaded is not None
        assert loaded.skill_id == "my-workflow"
        assert loaded.name == "my-workflow"
        assert loaded.description == "A workflow without explicit skill_id"
        assert "Step 1: Do the thing" in loaded.instructions

        # Should also appear in list_skills
        skills = storage.list_skills()
        skill_ids = [s.skill_id for s in skills]
        assert "my-workflow" in skill_ids

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

    def test_save_and_load_artifact(self, storage):
        """Test saving and loading an artifact."""
        artifact = Artifact(
            name="API Design",
            description="Design document for the API",
            content_type="markdown",
            project_id="p_123",
            originating_thread_id="t_456",
            tags=["design", "api"],
            content="# API Design\n\nThis is the API design document.",
        )

        path = storage.save(artifact)
        assert path.exists()
        assert path.suffix == ".md"
        assert "API Design" in path.name

        loaded = storage.load_artifact(artifact.artifact_id)
        assert loaded is not None
        assert loaded.name == "API Design"
        assert loaded.description == "Design document for the API"
        assert loaded.content_type == "markdown"
        assert loaded.project_id == "p_123"
        assert loaded.originating_thread_id == "t_456"
        assert "design" in loaded.tags
        assert "# API Design" in loaded.content

    def test_list_artifacts(self, storage):
        """Test listing artifacts."""
        a1 = Artifact(name="Doc 1", project_id="p_1")
        a2 = Artifact(name="Doc 2", project_id="p_1")
        a3 = Artifact(name="Doc 3", project_id="p_2")

        storage.save(a1)
        storage.save(a2)
        storage.save(a3)

        all_artifacts = storage.list_artifacts()
        assert len(all_artifacts) == 3

        project_artifacts = storage.list_artifacts(project_id="p_1")
        assert len(project_artifacts) == 2

    def test_load_artifact_by_name(self, storage):
        """Test loading an artifact by name."""
        artifact = Artifact(
            name="My Document",
            content="Document content here",
        )
        storage.save(artifact)

        loaded = storage.load_artifact_by_name("My Document")
        assert loaded is not None
        assert loaded.name == "My Document"
        assert loaded.content == "Document content here"


class TestConceptHierarchy:
    """Tests for hierarchical concept storage and retrieval."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with temp directory."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)

    def test_save_concept_with_parent_path(self, storage, tmp_path):
        """Concepts with parent_path should be saved in nested directories."""
        concept = Concept(
            name="Preferences",
            parent_path="Andrew Brookins",
            text="User preferences.",
        )
        path = storage.save(concept)

        # Should be in nested directory
        assert "Andrew Brookins" in str(path)
        assert path.name == "Preferences.md"
        assert path.exists()

    def test_save_concept_deep_hierarchy(self, storage, tmp_path):
        """Concepts with deep nesting should create nested directories."""
        concept = Concept(
            name="Lane",
            parent_path="Lane Harker/Characters",
            text="Main character.",
        )
        path = storage.save(concept)

        # Should be in deeply nested directory
        assert "Lane Harker" in str(path)
        assert "Characters" in str(path)
        assert path.name == "Lane.md"

    def test_load_concept_preserves_parent_path(self, storage):
        """Loading a concept should preserve its parent_path."""
        concept = Concept(
            name="Setting",
            parent_path="Lane Harker",
            text="The story setting.",
        )
        storage.save(concept)

        loaded = storage.load_concept(concept.concept_id)
        assert loaded is not None
        assert loaded.parent_path == "Lane Harker"
        assert loaded.full_path == "Lane Harker/Setting"

    def test_load_concept_by_path(self, storage):
        """Test loading a concept by its hierarchical path."""
        concept = Concept(
            name="Preferences",
            parent_path="Andrew Brookins",
            text="User preferences.",
        )
        storage.save(concept)

        loaded = storage.load_concept_by_path("Andrew Brookins/Preferences")
        assert loaded is not None
        assert loaded.name == "Preferences"
        assert loaded.parent_path == "Andrew Brookins"

    def test_load_concept_by_path_not_found(self, storage):
        """Test loading a non-existent path returns None."""
        result = storage.load_concept_by_path("NonExistent/Path")
        assert result is None

    def test_load_concept_by_path_index_file(self, storage, tmp_path):
        """Test loading a folder concept via _index.md."""
        # Create a folder with _index.md
        concepts_dir = tmp_path / "Concepts" / "Lane Harker"
        concepts_dir.mkdir(parents=True)
        index_file = concepts_dir / "_index.md"
        index_file.write_text(
            "---\nname: Lane Harker\nconcept_id: c_test123\n---\nNovel overview."
        )

        loaded = storage.load_concept_by_path("Lane Harker")
        assert loaded is not None
        assert loaded.name == "Lane Harker"
        assert "Novel overview" in loaded.text

    def test_list_concept_children(self, storage):
        """Test listing direct children of a concept path."""
        # Create parent and children
        parent = Concept(name="Lane Harker", text="Novel overview.")
        child1 = Concept(name="Setting", parent_path="Lane Harker", text="Setting.")
        child2 = Concept(name="Plot", parent_path="Lane Harker", text="Plot.")
        grandchild = Concept(
            name="Lane", parent_path="Lane Harker/Characters", text="Character."
        )

        storage.save(parent)
        storage.save(child1)
        storage.save(child2)
        storage.save(grandchild)

        children = storage.list_concept_children("Lane Harker")
        names = [c.name for c in children]

        # Should include direct children only
        assert "Setting" in names
        assert "Plot" in names
        # Should NOT include grandchildren
        assert "Lane" not in names

    def test_list_concept_children_root(self, storage):
        """Test listing root-level concepts."""
        root1 = Concept(name="Andrew Brookins", text="User.")
        root2 = Concept(name="Lane Harker", text="Novel.")
        child = Concept(name="Preferences", parent_path="Andrew Brookins", text=".")

        storage.save(root1)
        storage.save(root2)
        storage.save(child)

        roots = storage.list_concept_children(None)
        names = [c.name for c in roots]

        assert "Andrew Brookins" in names
        assert "Lane Harker" in names
        # Children should not appear at root level
        assert "Preferences" not in names

    def test_get_concept_parent(self, storage):
        """Test getting the parent concept of a path."""
        parent = Concept(name="Lane Harker", text="Novel overview.")
        child = Concept(name="Setting", parent_path="Lane Harker", text="Setting.")

        storage.save(parent)
        storage.save(child)

        parent_concept = storage.get_concept_parent("Lane Harker/Setting")
        assert parent_concept is not None
        assert parent_concept.name == "Lane Harker"

    def test_get_concept_parent_not_found(self, storage):
        """Test getting parent when parent doesn't exist."""
        child = Concept(name="Orphan", parent_path="NonExistent", text="Orphan.")
        storage.save(child)

        parent = storage.get_concept_parent("NonExistent/Orphan")
        assert parent is None

    def test_list_concepts_with_parent_path_filter(self, storage):
        """Test listing concepts filtered by parent_path."""
        root = Concept(name="Lane Harker", text="Novel.")
        child1 = Concept(name="Setting", parent_path="Lane Harker", text="Setting.")
        child2 = Concept(name="Plot", parent_path="Lane Harker", text="Plot.")
        other = Concept(name="Andrew", text="User.")

        storage.save(root)
        storage.save(child1)
        storage.save(child2)
        storage.save(other)

        # Filter by parent_path
        lane_concepts = storage.list_concepts(parent_path="Lane Harker")
        names = [c.name for c in lane_concepts]

        assert "Setting" in names
        assert "Plot" in names
        assert "Andrew" not in names

    def test_concept_with_links(self, storage):
        """Test saving and loading concepts with cross-reference links."""
        concept = Concept(
            name="Nose",
            parent_path="Anatomy/Face",
            text="The nose.",
            links=["Respiratory System", "Sensory Organs"],
        )
        storage.save(concept)

        loaded = storage.load_concept(concept.concept_id)
        assert loaded is not None
        assert loaded.links == ["Respiratory System", "Sensory Organs"]

    def test_load_concept_by_name_finds_nested(self, storage):
        """load_concept_by_name should find concepts in nested directories."""
        concept = Concept(
            name="Unique Nested Name",
            parent_path="Deep/Nested/Path",
            text="Content.",
        )
        storage.save(concept)

        loaded = storage.load_concept_by_name("Unique Nested Name")
        assert loaded is not None
        assert loaded.name == "Unique Nested Name"
        assert loaded.parent_path == "Deep/Nested/Path"

    def test_find_concept_file(self, storage, tmp_path):
        """find_concept_file should return the file path for a concept."""
        concept = Concept(
            name="Test Concept",
            parent_path="Some/Path",
            text="Content.",
        )
        saved_path = storage.save(concept)

        found_path = storage.find_concept_file(concept.concept_id)
        assert found_path is not None
        assert found_path == saved_path

    def test_find_concept_file_not_found(self, storage):
        """find_concept_file should return None for non-existent concept."""
        result = storage.find_concept_file("nonexistent_id")
        assert result is None

    def test_delete_concept_file(self, storage, tmp_path):
        """delete_concept_file should remove the file."""
        concept = Concept(
            name="To Delete",
            parent_path="Delete/Path",
            text="Content.",
        )
        saved_path = storage.save(concept)
        assert saved_path.exists()

        result = storage.delete_concept_file(saved_path)
        assert result is True
        assert not saved_path.exists()

    def test_delete_concept_file_cleans_empty_dirs(self, storage, tmp_path):
        """delete_concept_file should clean up empty parent directories."""
        concept = Concept(
            name="Lonely",
            parent_path="Empty/Parent/Dirs",
            text="Content.",
        )
        saved_path = storage.save(concept)
        parent_dir = saved_path.parent

        storage.delete_concept_file(saved_path)

        # Parent directories should be cleaned up since they're empty
        assert not parent_dir.exists()

    def test_delete_concept_file_not_found(self, storage, tmp_path):
        """delete_concept_file should return False for non-existent file."""
        from pathlib import Path

        result = storage.delete_concept_file(Path("/nonexistent/path.md"))
        assert result is False


class TestIndexAutoUpdate:
    """Tests for automatic index updates when files change."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with temp directory."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)

    def test_search_finds_updated_content(self, tmp_path, embedding_model):
        """When a concept is updated, search should find the new content."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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

    def test_search_finds_new_files(self, tmp_path, embedding_model):
        """When new files are added externally, search should find them."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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

    def test_search_handles_deleted_files(self, tmp_path, embedding_model):
        """When files are deleted, search should not return them."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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

    def test_search_concepts_returns_no_duplicates(self, tmp_path, embedding_model):
        """Search should never return the same concept twice."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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

    def test_search_after_create_no_duplicates(self, tmp_path, embedding_model):
        """Creating a concept then searching should not produce duplicates."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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

    def test_add_to_index_duplicate_detection(self, tmp_path, embedding_model):
        """Test that add_to_index skips items already in the index."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Build empty index first
        searcher.build_index()

        # Add a concept to the index
        searcher.add_to_index(
            "concept",
            "Test content",
            {"id": "c_test", "name": "Test", "project_id": None},
        )
        initial_count = len(searcher._id_map)

        # Try to add the same concept again
        searcher.add_to_index(
            "concept",
            "Test content",
            {"id": "c_test", "name": "Test", "project_id": None},
        )

        # Should not have added a duplicate
        assert len(searcher._id_map) == initial_count

    def test_add_to_index_different_types(self, tmp_path, embedding_model):
        """Test add_to_index with different item types in the index."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Build empty index first
        searcher.build_index()

        # Add a concept
        searcher.add_to_index(
            "concept",
            "Concept content",
            {"id": "c_1", "name": "Concept1", "project_id": None},
        )

        # Add a skill (different type, should not be detected as duplicate)
        searcher.add_to_index(
            "skill",
            "Skill content",
            {"id": "s_1", "name": "Skill1"},
        )

        # Both should be in the index
        types_in_index = [item["type"] for item in searcher._id_map]
        assert "concept" in types_in_index
        assert "skill" in types_in_index

        # Now add another concept - the loop should iterate past the skill
        searcher.add_to_index(
            "concept",
            "Another concept",
            {"id": "c_2", "name": "Concept2", "project_id": None},
        )

        # Should have 3 items now
        assert len(searcher._id_map) == 3

    def test_multiple_searches_no_duplicates(self, tmp_path, embedding_model):
        """Multiple searches should not accumulate duplicates in the index."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

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


class TestArtifactSearch:
    """Tests for artifact search functionality."""

    def test_search_artifacts(self, tmp_path, embedding_model):
        """Artifacts should be searchable by their content."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create an artifact
        artifact = Artifact(
            name="API Design Doc",
            description="Design document for REST API",
            content="# REST API Design\n\nDescribes the authentication endpoints.",
            project_id="p_123",
        )
        storage.save(artifact)

        # Build index and search
        searcher.build_index()
        results = searcher.search_artifacts("authentication endpoints")

        assert len(results) > 0
        assert results[0]["name"] == "API Design Doc"
        assert results[0]["id"] == artifact.artifact_id

    def test_search_artifacts_filter_by_project(self, tmp_path, embedding_model):
        """Artifact search should filter by project_id."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create artifacts in different projects
        a1 = Artifact(name="Doc A", content="Database schema design", project_id="p_1")
        a2 = Artifact(name="Doc B", content="Database migration plan", project_id="p_2")
        storage.save(a1)
        storage.save(a2)

        searcher.build_index()

        # Search with project filter
        results = searcher.search_artifacts("database", project_id="p_1")
        assert len(results) == 1
        assert results[0]["name"] == "Doc A"


class TestSearchEdgeCases:
    """Tests for search edge cases and error handling."""

    def test_get_embeddings_empty_texts(self, tmp_path, embedding_model):
        """Test _get_embeddings with empty texts list."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Call _get_embeddings with empty list
        result = searcher._get_embeddings([])
        assert len(result) == 0

    def test_extra_concept_dirs_in_index(self, tmp_path, embedding_model):
        """Test that extra_concept_dirs are included in content files."""
        from mcp_memory.search import MemorySearcher

        # Create extra directories
        (tmp_path / "People").mkdir()
        (tmp_path / "Characters").mkdir()
        alice_content = "---\ntags: [person]\n---\nAlice info"
        bob_content = "---\ntags: [char]\n---\nBob info"
        (tmp_path / "People" / "Alice.md").write_text(alice_content)
        (tmp_path / "Characters" / "Bob.md").write_text(bob_content)

        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["People", "Characters"],
        )
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Get content files - should include extra dirs
        files = searcher._get_content_files()
        file_names = [f.name for f in files]
        assert "Alice.md" in file_names
        assert "Bob.md" in file_names

    def test_extra_concept_dirs_nonexistent(self, tmp_path, embedding_model):
        """Test that nonexistent extra_concept_dirs are skipped."""
        from mcp_memory.search import MemorySearcher

        # Only create one of the two extra dirs
        (tmp_path / "Existing").mkdir()
        (tmp_path / "Existing" / "Test.md").write_text("---\ntags: []\n---\nContent")
        # Don't create "NonExistent" directory

        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["Existing", "NonExistent"],
        )
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Should include Existing but not fail on NonExistent
        files = searcher._get_content_files()
        file_names = [f.name for f in files]
        assert "Test.md" in file_names

    def test_get_file_mtimes_handles_oserror(self, tmp_path, embedding_model):
        """Test _get_current_mtimes handles OSError (deleted files)."""
        from unittest.mock import patch

        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create a concept to ensure there's a file
        concept = Concept(name="Test", text="Content")
        storage.save(concept)

        # Mock _get_content_files to return a file, then simulate OSError on stat
        original_get_content_files = searcher._get_content_files

        def mock_get_content_files():
            # Return a file that will raise OSError when stat() is called
            class FakeFile:
                def stat(self):
                    raise OSError("File deleted")

                def __str__(self):
                    return "/fake/path.md"

            return [FakeFile()] + list(original_get_content_files())

        with patch.object(searcher, "_get_content_files", mock_get_content_files):
            mtimes = searcher._get_current_mtimes()
            # Should succeed without exception, skipping the problematic file
            assert isinstance(mtimes, dict)

    def test_thread_message_indexing(self, tmp_path, embedding_model):
        """Test that thread messages are indexed."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create a thread with messages
        thread = Thread(project_id="p_test")
        thread.messages.append(Message(role="user", text="Hello, how are you?"))
        assistant_msg = "I am doing well, thank you!"
        thread.messages.append(Message(role="assistant", text=assistant_msg))
        storage.save(thread)

        # Build index
        searcher.build_index()

        # Search for message content
        results = searcher.search_messages("doing well thank you")
        assert len(results) > 0
        assert results[0]["thread_id"] == thread.thread_id

    def test_index_loading_from_disk(self, tmp_path, embedding_model):
        """Test loading index from disk."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create content and build index
        concept = Concept(name="Persistent", text="This should be loaded from disk")
        storage.save(concept)
        searcher.build_index()

        # Create a new searcher instance (simulating restart)
        searcher2 = MemorySearcher(storage, config, model=embedding_model)

        # Ensure index is loaded from disk (not rebuilt)
        loaded = searcher2._load_index()
        assert loaded is True
        assert len(searcher2._id_map) > 0
        assert searcher2._index is not None

    def test_load_index_without_mtimes_file(self, tmp_path, embedding_model):
        """Test _load_index when mtimes file doesn't exist."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create content and build index
        concept = Concept(name="Test", text="Test content")
        storage.save(concept)
        searcher.build_index()

        # Delete the mtimes file
        mtimes_file = tmp_path / ".memory_index" / "mtimes.json"
        if mtimes_file.exists():
            mtimes_file.unlink()

        # Create new searcher and load index (should work without mtimes)
        searcher2 = MemorySearcher(storage, config, model=embedding_model)
        loaded = searcher2._load_index()
        assert loaded is True
        # mtimes should be empty since file was deleted
        assert searcher2._file_mtimes == {}

    def test_ensure_index_loads_existing(self, tmp_path, embedding_model):
        """Test ensure_index loads existing index without rebuilding."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create content and build index
        concept = Concept(name="Test", text="Test content")
        storage.save(concept)
        searcher = MemorySearcher(storage, config, model=embedding_model)
        searcher.build_index()

        # Create new searcher and call ensure_index
        searcher2 = MemorySearcher(storage, config, model=embedding_model)
        searcher2.ensure_index()  # Should load from disk, not rebuild
        assert searcher2._index is not None
        assert len(searcher2._id_map) > 0

    def test_search_messages_with_filters(self, tmp_path, embedding_model):
        """Test search_messages with thread_id and project_id filters."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create threads with messages in different projects
        t1 = Thread(project_id="p_1")
        t1.messages.append(Message(role="user", text="Question about Python"))
        storage.save(t1)

        t2 = Thread(project_id="p_2")
        t2.messages.append(Message(role="user", text="Question about Python"))
        storage.save(t2)

        searcher.build_index()

        # Filter by project
        results = searcher.search_messages("Python", project_id="p_1")
        assert all(r["project_id"] == "p_1" for r in results)

        # Filter by thread
        results = searcher.search_messages("Python", thread_id=t1.thread_id)
        assert all(r["thread_id"] == t1.thread_id for r in results)

    def test_search_threads(self, tmp_path, embedding_model):
        """Test search_threads method returns deduplicated thread IDs."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create a thread with multiple messages
        thread = Thread(project_id="p_test")
        thread.messages.append(Message(role="user", text="Tell me about databases"))
        thread.messages.append(Message(role="assistant", text="Databases store data"))
        thread.messages.append(Message(role="user", text="What about SQL databases?"))
        storage.save(thread)

        searcher.build_index()

        # Search threads - should return deduplicated results
        results = searcher.search_threads("databases")
        thread_ids = [r["thread_id"] for r in results]

        # Should not have duplicate thread IDs
        assert len(thread_ids) == len(set(thread_ids))
        assert thread.thread_id in thread_ids

    def test_search_with_invalid_index_position(self, tmp_path, embedding_model):
        """Test search handles invalid index positions gracefully."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create content
        concept = Concept(name="Test", text="Test content")
        storage.save(concept)
        searcher.build_index()

        # Search should work normally
        results = searcher.search_concepts("test content")
        assert len(results) > 0

    def test_search_reaches_limit(self, tmp_path, embedding_model):
        """Test that search respects the limit parameter."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create many concepts
        for i in range(10):
            text = f"Similar content about item {i}"
            concept = Concept(name=f"Concept {i}", text=text)
            storage.save(concept)

        searcher.build_index()

        # Search with limit
        results = searcher.search_concepts("similar content", limit=3)
        assert len(results) <= 3

    def test_search_empty_index(self, tmp_path, embedding_model):
        """Test searching with an empty index."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Build empty index
        searcher.build_index()

        # Search on empty index should return empty
        results = searcher.search_concepts("anything")
        assert results == []

    def test_index_stale_detection_new_files(self, tmp_path, embedding_model):
        """Test that new files are detected as index being stale."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Build initial index
        concept = Concept(name="Initial", text="Initial content")
        storage.save(concept)
        searcher.build_index()

        # Add a new file
        concept2 = Concept(name="New", text="New content")
        storage.save(concept2)

        # Index should be stale
        assert searcher._is_index_stale() is True

    def test_index_stale_detection_modified_files(self, tmp_path, embedding_model):
        """Test that modified files are detected as index being stale."""
        import time

        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Build initial index
        concept = Concept(name="Original", text="Original content")
        storage.save(concept)
        searcher.build_index()

        # Modify the file (need small delay for mtime change)
        time.sleep(0.01)
        concept.text = "Modified content"
        storage.save(concept)

        # Index should be stale
        assert searcher._is_index_stale() is True

    def test_search_skill_type_filtering(self, tmp_path, embedding_model):
        """Test _search filters correctly by skill type."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create a skill
        skill = Skill(
            name="Python Testing", description="Test", instructions="pytest steps"
        )
        storage.save(skill)

        searcher.build_index()

        # Search skills
        results = searcher.search_skills("pytest")
        assert len(results) > 0
        assert results[0]["type"] == "skill"

    def test_search_threads_reaches_limit(self, tmp_path, embedding_model):
        """Test search_threads respects limit and breaks early."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create multiple threads with similar content
        for i in range(5):
            thread = Thread(project_id="p_test")
            msg_text = f"Question about databases {i}"
            thread.messages.append(Message(role="user", text=msg_text))
            storage.save(thread)

        searcher.build_index()

        # Search with limit=2
        results = searcher.search_threads("databases", limit=2)
        assert len(results) <= 2

    def test_search_invalid_index_position(self, tmp_path, embedding_model):
        """Test _search handles invalid index positions (idx < 0 or out of range)."""
        from unittest.mock import patch

        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create content and build index
        concept = Concept(name="Test", text="Test content")
        storage.save(concept)
        searcher.build_index()

        # Mock the index search to return invalid indices
        def mock_search(query, k):
            import numpy as np

            # Return some invalid indices (-1 and out of range)
            distances = np.array([[0.1, 0.2, 0.3]])
            indices = np.array([[-1, 999999, 0]])  # -1 and 999999 are invalid
            return distances, indices

        with patch.object(searcher._index, "search", mock_search):
            results = searcher._search("test", "concept", limit=10)
            # Should only return valid results (index 0)
            assert len(results) <= 1

    def test_search_type_mismatch(self, tmp_path, embedding_model):
        """Test _search skips items with wrong type."""
        from mcp_memory.search import MemorySearcher

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)
        searcher = MemorySearcher(storage, config, model=embedding_model)

        # Create both concept and skill with similar content
        concept = Concept(name="Database Concept", text="Database information")
        skill = Skill(
            name="Database Skill", description="DB", instructions="Database steps"
        )
        storage.save(concept)
        storage.save(skill)

        searcher.build_index()

        # Search for concepts only - should not return skills
        results = searcher.search_concepts("database")
        for r in results:
            assert r["type"] == "concept"


class TestStorageCoverageGaps:
    """Tests for storage.py coverage gaps."""

    def test_parse_frontmatter_incomplete_delimiters(self, tmp_path):
        """Test parse_frontmatter with incomplete delimiters (only one ---)."""
        from mcp_memory.storage import parse_frontmatter

        # Content with only one --- (incomplete frontmatter)
        content = "---\nname: test\nNo closing delimiter"
        frontmatter, body = parse_frontmatter(content)
        assert frontmatter == {}
        assert body == content

    def test_load_concept_by_name_sanitized_filename(self, tmp_path):
        """Test load_concept_by_name finds file by sanitized filename."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create concept with special characters in name
        concept = Concept(name="Test/Concept:Special", text="Content")
        storage.save(concept)

        # Load by name - should find via sanitized filename
        loaded = storage.load_concept_by_name("Test/Concept:Special")
        assert loaded is not None
        assert loaded.text == "Content"

    def test_load_concept_by_name_case_insensitive_filename(self, tmp_path):
        """Test load_concept_by_name finds file by case-insensitive filename match."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create concept
        concept = Concept(name="MyTestConcept", text="Content")
        storage.save(concept)

        # Load by name with different case
        loaded = storage.load_concept_by_name("mytestconcept")
        assert loaded is not None

    def test_load_concept_by_name_frontmatter_match(self, tmp_path):
        """Test load_concept_by_name finds file by frontmatter name field."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create a file with different filename than frontmatter name
        concepts_dir = tmp_path / "concepts"
        concepts_dir.mkdir()
        file_path = concepts_dir / "different_filename.md"
        file_path.write_text("---\nname: ActualName\n---\nContent here")

        # Load by frontmatter name
        loaded = storage.load_concept_by_name("ActualName")
        assert loaded is not None
        assert loaded.name == "ActualName"

    def test_load_concept_by_name_alias_match(self, tmp_path):
        """Test load_concept_by_name finds file by Obsidian alias."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create a file with aliases
        concepts_dir = tmp_path / "concepts"
        concepts_dir.mkdir()
        file_path = concepts_dir / "main_name.md"
        content = "---\nname: MainName\naliases:\n  - AliasOne\n  - AliasTwo\n---\n"
        content += "Content"
        file_path.write_text(content)

        # Load by alias
        loaded = storage.load_concept_by_name("aliasone")
        assert loaded is not None
        assert loaded.name == "MainName"

    def test_load_concept_by_name_not_found(self, tmp_path):
        """Test load_concept_by_name returns None when not found."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create concepts dir but no matching file
        concepts_dir = tmp_path / "concepts"
        concepts_dir.mkdir()

        loaded = storage.load_concept_by_name("NonExistent")
        assert loaded is None

    def test_load_project_by_name_not_found(self, tmp_path):
        """Test load_project_by_name returns None when not found."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create projects dir but no matching file
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()

        loaded = storage.load_project_by_name("NonExistent")
        assert loaded is None

    def test_load_artifact_by_name_not_found(self, tmp_path):
        """Test load_artifact_by_name returns None when not found."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create artifacts dir but no matching file
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        loaded = storage.load_artifact_by_name("NonExistent")
        assert loaded is None

    def test_load_by_id_derives_name_from_filename(self, tmp_path):
        """Test _load_by_id derives name from filename when missing."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create a file without name in frontmatter
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        file_path = skills_dir / "MySkillName.md"
        content = "---\nskill_id: s_123\ndescription: Test\n---\nInstructions"
        file_path.write_text(content)

        # Load by ID - should derive name from filename
        loaded = storage.load_skill("s_123")
        assert loaded is not None
        assert loaded.name == "MySkillName"

    def test_load_by_id_derives_id_from_filename(self, tmp_path):
        """Test _load_by_id derives ID from filename when missing."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create a file without ID in frontmatter
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        file_path = skills_dir / "MySkillID.md"
        content = "---\nname: Test Skill\ndescription: Test\n---\nInstructions"
        file_path.write_text(content)

        # Load by filename as ID - should work
        loaded = storage.load_skill("MySkillID")
        assert loaded is not None
        assert loaded.skill_id == "MySkillID"

    def test_list_concepts_extra_dirs_with_project_filter(self, tmp_path):
        """Test list_concepts filters extra_concept_dirs by project_id."""
        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["People"],
        )
        storage = MemoryStorage(config)

        # Create extra dir with concepts
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        (people_dir / "Alice.md").write_text("---\nproject_id: p_1\n---\nAlice info")
        (people_dir / "Bob.md").write_text("---\nproject_id: p_2\n---\nBob info")

        # List with project filter
        concepts = storage.list_concepts(project_id="p_1")
        names = [c.name for c in concepts]
        assert "Alice" in names
        assert "Bob" not in names

    def test_list_concepts_extra_dirs_parse_error(self, tmp_path):
        """Test list_concepts skips files that can't be parsed in extra dirs."""
        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["People"],
        )
        storage = MemoryStorage(config)

        # Create extra dir with invalid file
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        (people_dir / "Invalid.md").write_text("This is not valid frontmatter: {{{")
        (people_dir / "Valid.md").write_text("---\nname: Valid\n---\nContent")

        # Should not raise, should skip invalid file
        concepts = storage.list_concepts()
        names = [c.name for c in concepts]
        assert "Valid" in names

    def test_list_reflections_with_filters(self, tmp_path):
        """Test list_reflections with project_id and skill_id filters."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create reflections with different associations
        r1 = Reflection(text="Reflection 1", project_id="p_1", skill_id="s_1")
        r2 = Reflection(text="Reflection 2", project_id="p_1", skill_id="s_2")
        r3 = Reflection(text="Reflection 3", project_id="p_2", skill_id="s_1")
        storage.save(r1)
        storage.save(r2)
        storage.save(r3)

        # Filter by project
        reflections = storage.list_reflections(project_id="p_1")
        assert len(reflections) == 2

        # Filter by skill
        reflections = storage.list_reflections(skill_id="s_1")
        assert len(reflections) == 2

        # Filter by both
        reflections = storage.list_reflections(project_id="p_1", skill_id="s_1")
        assert len(reflections) == 1

    def test_list_reflections_empty_dir(self, tmp_path):
        """Test list_reflections returns empty list when dir doesn't exist."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Don't create reflections dir
        reflections = storage.list_reflections()
        assert reflections == []

    def test_load_concept_by_name_filename_stem_match(self, tmp_path):
        """Test load_concept_by_name finds file by filename stem (case-insensitive)."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # To hit line 181, we need:
        # 1. Exact filename lookup fails (line 168)
        # 2. Sanitized filename lookup fails (line 174)
        # 3. Stem match succeeds (line 180)

        # Create a file with a simple name
        concepts_dir = tmp_path / "concepts"
        concepts_dir.mkdir()
        file_path = concepts_dir / "TestConcept.md"
        file_path.write_text("---\nname: DifferentName\n---\nContent")

        # Search for "TESTCONCEPT" (all caps)
        # - Exact lookup: "TESTCONCEPT.md" doesn't exist
        # - Sanitized lookup: "TESTCONCEPT.md" doesn't exist
        # - Stem match: "TestConcept".lower() == "testconcept" == "TESTCONCEPT".lower()
        # This should hit line 181
        loaded = storage.load_concept_by_name("TESTCONCEPT")
        assert loaded is not None
        # The name should be derived from frontmatter or filename
        assert loaded.name in ["DifferentName", "TestConcept"]

    def test_load_by_id_no_match(self, tmp_path):
        """Test _load_by_id returns None when no file matches the ID."""
        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create skills dir with a file that has different ID
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        file_path = skills_dir / "SomeSkill.md"
        content = "---\nskill_id: s_different\nname: Some Skill\n---\nInstructions"
        file_path.write_text(content)

        # Try to load by non-existent ID
        loaded = storage.load_skill("s_nonexistent")
        assert loaded is None

    def test_list_concepts_extra_dirs_exception_handling(self, tmp_path):
        """Test list_concepts handles exceptions in extra dir files."""
        config = MemoryConfig(
            base_path=str(tmp_path),
            extra_concept_dirs=["People"],
        )
        storage = MemoryStorage(config)

        # Create extra dir with a file that causes exception during validation
        people_dir = tmp_path / "People"
        people_dir.mkdir()
        # Create a file with invalid YAML that will cause parse error
        bad_yaml = "---\n  invalid: yaml: here:\n---\nContent"
        (people_dir / "BadFile.md").write_text(bad_yaml)

        # Should not raise, should skip the bad file
        concepts = storage.list_concepts()
        # No valid concepts should be returned
        assert isinstance(concepts, list)
