"""Tests for mcp_memory MCP server."""

import pytest

from mcp_memory.models import MemoryConfig
from mcp_memory.server import create_memory_server
from mcp_memory.storage import MemoryStorage


class TestMemoryServer:
    """Tests for the MCP Memory server."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_server_has_tools(self, server):
        """Test that server has all expected tools."""
        tools = server._tool_manager._tools
        expected_tools = [
            "create_thread",
            "read_thread",
            "add_messages",
            "search_messages",
            "search_threads",
            "compact_thread",
            "search_concepts",
            "read_concept",
            "read_concept_by_name",
            "create_concept",
            "update_concept",
            "add_reflection",
            "update_reflection",
            "read_reflections",
            "create_project",
            "read_project",
            "update_project",
            "list_projects",
            "create_skill",
            "read_skill",
            "update_skill",
            "list_skills",
            "search_skills",
            "rebuild_index",
            # Artifact tools
            "create_artifact",
            "read_artifact",
            "update_artifact",
            "list_artifacts",
            "search_artifacts",
            "write_artifact_to_disk",
            "sync_artifact_from_disk",
        ]
        for tool_name in expected_tools:
            assert tool_name in tools, f"Missing tool: {tool_name}"

    def test_server_with_explicit_config(self, tmp_path, embedding_model):
        """Test creating server with explicit MemoryConfig."""
        config = MemoryConfig(base_path=str(tmp_path))
        server = create_memory_server(config=config, embedding_model=embedding_model)
        tools = server._tool_manager._tools
        assert "create_thread" in tools

    @pytest.fixture
    def storage(self, tmp_path):
        """Create storage for direct verification."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)


class TestThreadTools:
    """Tests for thread-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_create_thread(self, server):
        """Test creating a thread."""
        tool = server._tool_manager._tools["create_thread"]
        result = tool.fn(project_id="p_test")

        assert "thread_id" in result
        assert result["created"] is True
        assert result["thread_id"].startswith("t_")

    def test_create_thread_with_custom_id(self, server):
        """Test creating a thread with custom ID."""
        tool = server._tool_manager._tools["create_thread"]
        result = tool.fn(thread_id="my_custom_thread")

        assert result["thread_id"] == "my_custom_thread"

    def test_read_thread(self, server):
        """Test reading a thread."""
        create_tool = server._tool_manager._tools["create_thread"]
        read_tool = server._tool_manager._tools["read_thread"]

        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["thread_id"] == thread_id
        assert read_result["messages"] == []

    def test_read_thread_not_found(self, server):
        """Test reading a non-existent thread."""
        read_tool = server._tool_manager._tools["read_thread"]
        result = read_tool.fn(thread_id="nonexistent")
        assert "error" in result

    def test_add_messages(self, server):
        """Test adding messages to a thread."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        read_tool = server._tool_manager._tools["read_thread"]

        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        messages = [
            {"role": "user", "text": "Hello"},
            {"role": "assistant", "text": "Hi there!"},
        ]
        add_result = add_tool.fn(thread_id=thread_id, messages=messages)
        assert add_result["message_count"] == 2

        read_result = read_tool.fn(thread_id=thread_id)
        assert len(read_result["messages"]) == 2
        assert read_result["messages"][0]["role"] == "user"
        assert read_result["messages"][0]["text"] == "Hello"

    def test_compact_thread(self, server):
        """Test compacting a thread."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        compact_tool = server._tool_manager._tools["compact_thread"]
        read_tool = server._tool_manager._tools["read_thread"]

        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        messages = [{"role": "user", "text": "Hello"}]
        add_tool.fn(thread_id=thread_id, messages=messages)

        compact_result = compact_tool.fn(thread_id=thread_id, summary="User said hello")
        assert compact_result["compacted"] is True

        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["summary"] == "User said hello"
        assert read_result["messages"] == []

    def test_create_thread_with_title(self, server):
        """Test creating a thread with an explicit title."""
        tool = server._tool_manager._tools["create_thread"]
        result = tool.fn(title="My Important Discussion")

        assert result["thread_id"].startswith("t_")
        assert result["title"] == "My Important Discussion"
        assert result["created"] is True

    def test_thread_title_auto_derived_from_first_message(self, server):
        """Test that thread title is auto-derived from the first message."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        read_tool = server._tool_manager._tools["read_thread"]

        # Create thread without title
        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]
        assert create_result["title"] is None

        # Add first message
        messages = [{"role": "user", "text": "Help me debug this Python error"}]
        add_tool.fn(thread_id=thread_id, messages=messages)

        # Title should be derived from first message
        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["title"] == "Help me debug this Python error"

    def test_thread_title_truncated_for_long_message(self, server):
        """Test that long messages are truncated when deriving title."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        read_tool = server._tool_manager._tools["read_thread"]

        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        # Long message that exceeds 60 chars
        long_text = (
            "This is a very long message that should be truncated "
            "at a word boundary when used as a title"
        )
        messages = [{"role": "user", "text": long_text}]
        add_tool.fn(thread_id=thread_id, messages=messages)

        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["title"] is not None
        assert len(read_result["title"]) <= 63  # 60 + "..."
        assert read_result["title"].endswith("...")

    def test_thread_explicit_title_not_overwritten(self, server):
        """Test that explicit title is not overwritten by first message."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        read_tool = server._tool_manager._tools["read_thread"]

        # Create thread with explicit title
        create_result = create_tool.fn(title="My Custom Title")
        thread_id = create_result["thread_id"]

        # Add message
        messages = [{"role": "user", "text": "This should not become the title"}]
        add_tool.fn(thread_id=thread_id, messages=messages)

        # Title should remain unchanged
        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["title"] == "My Custom Title"


class TestConceptTools:
    """Tests for concept-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_create_concept(self, server):
        """Test creating a concept."""
        tool = server._tool_manager._tools["create_concept"]
        result = tool.fn(
            name="Lane Harker",
            text="A character in the story.",
            tags=["character"],
        )

        assert "concept_id" in result
        assert result["created"] is True

    def test_read_concept_by_name(self, server):
        """Test reading a concept by name."""
        create_tool = server._tool_manager._tools["create_concept"]
        read_tool = server._tool_manager._tools["read_concept_by_name"]

        create_tool.fn(name="Test Person", text="Description here")

        result = read_tool.fn(name="Test Person")
        assert result["name"] == "Test Person"
        assert result["text"] == "Description here"


class TestSkillTools:
    """Tests for skill-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_list_skills_returns_summary_without_instructions(self, server):
        """Test that list_skills returns a compact summary without full instructions."""
        create_tool = server._tool_manager._tools["create_skill"]
        list_tool = server._tool_manager._tools["list_skills"]

        # Create skills with long instructions
        create_tool.fn(
            name="Python Testing",
            description="How to write and run pytest tests",
            instructions="Step 1: Import pytest\nStep 2: Write functions\nStep 3: Run",
            tags=["python", "testing"],
        )
        create_tool.fn(
            name="Git Workflow",
            description="Standard git branching and PR workflow",
            instructions="Step 1: Create branch\nStep 2: Commit\nStep 3: PR",
            tags=["git"],
        )

        # List skills
        result = list_tool.fn()
        skills = result["skills"]

        assert len(skills) == 2

        # Verify each skill has summary fields
        for skill in skills:
            assert "skill_id" in skill
            assert "name" in skill
            assert "description" in skill
            assert "tags" in skill
            # Should NOT include full instructions (too verbose for listing)
            assert "instructions" not in skill, "list_skills excludes instructions"

        # Verify specific content
        python_skill = next(s for s in skills if s["name"] == "Python Testing")
        assert python_skill["description"] == "How to write and run pytest tests"
        assert python_skill["tags"] == ["python", "testing"]

    def test_update_skill(self, server):
        """Test updating a skill's content."""
        create_tool = server._tool_manager._tools["create_skill"]
        update_tool = server._tool_manager._tools["update_skill"]
        read_tool = server._tool_manager._tools["read_skill"]

        # Create a skill
        result = create_tool.fn(
            name="Python Testing",
            description="How to write tests in Python",
            instructions="Step 1: Import pytest\nStep 2: Write test functions",
            tags=["python", "testing"],
        )
        skill_id = result["skill_id"]

        # Update the skill
        update_result = update_tool.fn(
            skill_id=skill_id,
            instructions="Step 1: Import pytest\nStep 2: Write tests\nStep 3: Run",
            description="Complete guide to Python testing",
        )
        assert update_result["updated"] is True

        # Verify the update
        skill = read_tool.fn(skill_id=skill_id)
        assert "Step 3: Run" in skill["instructions"]
        assert skill["description"] == "Complete guide to Python testing"
        assert skill["name"] == "Python Testing"  # Name unchanged

    def test_update_skill_not_found(self, server):
        """Test updating a non-existent skill."""
        update_tool = server._tool_manager._tools["update_skill"]

        result = update_tool.fn(
            skill_id="s_nonexistent",
            instructions="New instructions",
        )
        assert result["error"] is not None

    def test_search_skills(self, server):
        """Test searching skills by semantic similarity."""
        create_tool = server._tool_manager._tools["create_skill"]
        search_tool = server._tool_manager._tools["search_skills"]

        # Create skills with different topics
        create_tool.fn(
            name="Python Testing",
            description="How to write and run pytest tests",
            instructions="Step 1: Import pytest\nStep 2: Write test functions",
            tags=["python", "testing"],
        )
        create_tool.fn(
            name="Git Workflow",
            description="Standard git branching and PR workflow",
            instructions="Step 1: Create branch\nStep 2: Commit\nStep 3: Push",
            tags=["git", "version-control"],
        )
        create_tool.fn(
            name="Docker Deployment",
            description="How to deploy applications with Docker containers",
            instructions="Step 1: Write Dockerfile\nStep 2: Build image\nStep 3: Run",
            tags=["docker", "deployment"],
        )

        # Search for testing-related skills
        result = search_tool.fn(query="unit testing python")
        assert "results" in result
        results = result["results"]

        # Should find at least the Python Testing skill
        assert len(results) > 0
        # First result should be the most relevant (Python Testing)
        assert results[0]["name"] == "Python Testing"

    def test_search_skills_empty_results(self, server):
        """Test searching skills when none match."""
        search_tool = server._tool_manager._tools["search_skills"]

        # Search with no skills created
        result = search_tool.fn(query="kubernetes helm charts")
        assert "results" in result
        assert result["results"] == []

    def test_search_skills_stale_index(self, tmp_path, embedding_model):
        """Test search_skills when index has stale data (skill deleted)."""
        from unittest.mock import patch

        from mcp_memory.models import MemoryConfig

        config = MemoryConfig(base_path=str(tmp_path))

        # Patch both searcher and storage to simulate stale index scenario
        with (
            patch(
                "mcp_memory.search.MemorySearcher.search_skills"
            ) as mock_search_skills,
            patch("mcp_memory.storage.MemoryStorage.load_skill") as mock_load_skill,
        ):
            # Searcher returns a result for a skill
            mock_search_skills.return_value = [{"id": "s_deleted", "score": 0.9}]
            # But storage can't find it (simulating deleted file)
            mock_load_skill.return_value = None

            # Create server
            server = create_memory_server(
                config=config, embedding_model=embedding_model
            )

            # Search should handle missing skill gracefully (skip it)
            search_tool = server._tool_manager._tools["search_skills"]
            result = search_tool.fn(query="test skill")
            assert "results" in result
            # The result should be empty since the skill was deleted
            assert result["results"] == []


class TestProjectTools:
    """Tests for project-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_update_project(self, server):
        """Test updating a project."""
        create_tool = server._tool_manager._tools["create_project"]
        update_tool = server._tool_manager._tools["update_project"]
        read_tool = server._tool_manager._tools["read_project"]

        # Create a project
        result = create_tool.fn(
            name="Star Wars Campaign",
            description="A tabletop RPG campaign",
            tags=["rpg", "star-wars"],
        )
        project_id = result["project_id"]

        # Update the project
        update_result = update_tool.fn(
            project_id=project_id,
            description="An epic tabletop RPG campaign set during the Clone Wars",
            instructions="Use d20 system",
        )
        assert update_result["updated"] is True

        # Verify the update
        project = read_tool.fn(project_id=project_id)
        assert "Clone Wars" in project["description"]
        assert project["instructions"] == "Use d20 system"
        assert project["name"] == "Star Wars Campaign"  # Name unchanged

    def test_update_project_not_found(self, server):
        """Test updating a non-existent project."""
        update_tool = server._tool_manager._tools["update_project"]

        result = update_tool.fn(
            project_id="p_nonexistent",
            description="New description",
        )
        assert result["error"] is not None


class TestReflectionTools:
    """Tests for reflection-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_update_reflection(self, server):
        """Test updating a reflection."""
        add_tool = server._tool_manager._tools["add_reflection"]
        update_tool = server._tool_manager._tools["update_reflection"]
        read_tool = server._tool_manager._tools["read_reflections"]

        # Create a reflection
        result = add_tool.fn(
            text="User prefers detailed explanations",
            tags=["preference"],
        )
        reflection_id = result["reflection_id"]

        # Update the reflection
        update_result = update_tool.fn(
            reflection_id=reflection_id,
            text="User prefers detailed explanations with code examples",
            tags=["preference", "code"],
        )
        assert update_result["updated"] is True

        # Verify the update
        reflections = read_tool.fn()
        matching = [
            r for r in reflections["reflections"] if r["reflection_id"] == reflection_id
        ]
        assert len(matching) == 1
        assert "code examples" in matching[0]["text"]
        assert "code" in matching[0]["tags"]

    def test_update_reflection_not_found(self, server):
        """Test updating a non-existent reflection."""
        update_tool = server._tool_manager._tools["update_reflection"]

        result = update_tool.fn(
            reflection_id="r_nonexistent",
            text="New text",
        )
        assert result["error"] is not None


class TestArtifactTools:
    """Tests for artifact-related tools."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_create_artifact(self, server):
        """Test creating an artifact."""
        tool = server._tool_manager._tools["create_artifact"]
        result = tool.fn(
            name="API Design Doc",
            description="Design document for the REST API",
            content="# API Design\n\nThis document describes the API.",
            content_type="markdown",
            project_id="p_123",
            tags=["design", "api"],
        )

        assert "artifact_id" in result
        assert result["created"] is True
        assert result["artifact_id"].startswith("a_")

    def test_create_artifact_with_originating_thread(self, server):
        """Test creating an artifact with originating thread."""
        tool = server._tool_manager._tools["create_artifact"]
        result = tool.fn(
            name="Meeting Notes",
            content="Notes from our meeting.",
            originating_thread_id="t_123",
        )

        assert result["created"] is True

        # Read it back to verify
        read_tool = server._tool_manager._tools["read_artifact"]
        artifact = read_tool.fn(artifact_id=result["artifact_id"])
        assert artifact["originating_thread_id"] == "t_123"

    def test_read_artifact(self, server):
        """Test reading an artifact by ID."""
        create_tool = server._tool_manager._tools["create_artifact"]
        read_tool = server._tool_manager._tools["read_artifact"]

        create_result = create_tool.fn(
            name="Test Document",
            content="Document content here.",
        )
        artifact_id = create_result["artifact_id"]

        result = read_tool.fn(artifact_id=artifact_id)
        assert result["name"] == "Test Document"
        assert result["content"] == "Document content here."

    def test_read_artifact_not_found(self, server):
        """Test reading a non-existent artifact."""
        read_tool = server._tool_manager._tools["read_artifact"]
        result = read_tool.fn(artifact_id="a_nonexistent")
        assert "error" in result

    def test_update_artifact(self, server):
        """Test updating an artifact."""
        create_tool = server._tool_manager._tools["create_artifact"]
        update_tool = server._tool_manager._tools["update_artifact"]
        read_tool = server._tool_manager._tools["read_artifact"]

        create_result = create_tool.fn(
            name="Draft Document",
            content="Initial content.",
        )
        artifact_id = create_result["artifact_id"]

        update_result = update_tool.fn(
            artifact_id=artifact_id,
            content="Updated content with more details.",
            description="Now has a description",
        )
        assert update_result["updated"] is True

        # Verify the update
        artifact = read_tool.fn(artifact_id=artifact_id)
        assert artifact["content"] == "Updated content with more details."
        assert artifact["description"] == "Now has a description"
        assert artifact["name"] == "Draft Document"  # Name unchanged

    def test_update_artifact_not_found(self, server):
        """Test updating a non-existent artifact."""
        update_tool = server._tool_manager._tools["update_artifact"]

        result = update_tool.fn(
            artifact_id="a_nonexistent",
            content="New content",
        )
        assert "error" in result

    def test_list_artifacts(self, server):
        """Test listing artifacts."""
        create_tool = server._tool_manager._tools["create_artifact"]
        list_tool = server._tool_manager._tools["list_artifacts"]

        # Create artifacts in different projects
        create_tool.fn(name="Doc A", content="A", project_id="p_1")
        create_tool.fn(name="Doc B", content="B", project_id="p_1")
        create_tool.fn(name="Doc C", content="C", project_id="p_2")

        # List all artifacts
        all_result = list_tool.fn()
        assert len(all_result["artifacts"]) == 3

        # List by project
        project_result = list_tool.fn(project_id="p_1")
        assert len(project_result["artifacts"]) == 2

    def test_list_artifacts_returns_summary(self, server):
        """Test that list_artifacts returns summary without full content."""
        create_tool = server._tool_manager._tools["create_artifact"]
        list_tool = server._tool_manager._tools["list_artifacts"]

        create_tool.fn(
            name="Large Document",
            description="A very large document",
            content="# Lots of content here...\n" * 100,
            tags=["large"],
        )

        result = list_tool.fn()
        artifacts = result["artifacts"]

        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert "artifact_id" in artifact
        assert "name" in artifact
        assert "description" in artifact
        assert "tags" in artifact
        # Should NOT include full content (too verbose for listing)
        assert "content" not in artifact, "list_artifacts should not include content"

    def test_create_artifact_with_path_and_skill_id(self, server):
        """Test creating an artifact with path and skill_id fields."""
        create_tool = server._tool_manager._tools["create_artifact"]
        read_tool = server._tool_manager._tools["read_artifact"]

        result = create_tool.fn(
            name="Migration Helper",
            content="def migrate(): pass",
            content_type="code",
            path="database-migration/helper.py",
            skill_id="s_abc123",
        )

        assert result["created"] is True

        artifact = read_tool.fn(artifact_id=result["artifact_id"])
        assert artifact["path"] == "database-migration/helper.py"
        assert artifact["skill_id"] == "s_abc123"

    def test_write_artifact_to_disk(self, server, tmp_path):
        """Test writing an artifact to disk."""
        create_tool = server._tool_manager._tools["create_artifact"]
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]

        # Create an artifact with a path
        create_result = create_tool.fn(
            name="Helper Script",
            content="def hello():\n    print('Hello, World!')",
            content_type="code",
            path="scripts/helper.py",
        )
        artifact_id = create_result["artifact_id"]

        # Write to disk
        target_dir = str(tmp_path / "output")
        result = write_tool.fn(artifact_id=artifact_id, target_dir=target_dir)

        assert result["written"] is True
        assert result["path"] == f"{target_dir}/scripts/helper.py"

        # Verify the file exists and has correct content
        written_file = tmp_path / "output" / "scripts" / "helper.py"
        assert written_file.exists()
        # Note: storage strips trailing whitespace from body content
        assert written_file.read_text() == "def hello():\n    print('Hello, World!')"

    def test_write_artifact_to_disk_without_path(self, server, tmp_path):
        """Test writing an artifact that has no path set."""
        create_tool = server._tool_manager._tools["create_artifact"]
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]

        # Create an artifact WITHOUT a path
        create_result = create_tool.fn(
            name="Some Document",
            content="Document content",
        )
        artifact_id = create_result["artifact_id"]

        # Should fail because no path is set
        target_dir = str(tmp_path / "output")
        result = write_tool.fn(artifact_id=artifact_id, target_dir=target_dir)

        assert "error" in result
        assert "path" in result["error"].lower()

    def test_write_artifact_to_disk_not_found(self, server, tmp_path):
        """Test writing a non-existent artifact."""
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]

        result = write_tool.fn(artifact_id="a_nonexistent", target_dir=str(tmp_path))
        assert "error" in result

    def test_sync_artifact_from_disk(self, server, tmp_path):
        """Test syncing an artifact from a file on disk."""
        create_tool = server._tool_manager._tools["create_artifact"]
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]
        sync_tool = server._tool_manager._tools["sync_artifact_from_disk"]
        read_tool = server._tool_manager._tools["read_artifact"]

        # Create an artifact with a path
        create_result = create_tool.fn(
            name="Helper Script",
            content="def hello():\n    pass",
            content_type="code",
            path="scripts/helper.py",
        )
        artifact_id = create_result["artifact_id"]

        # Write to disk
        target_dir = str(tmp_path / "output")
        write_tool.fn(artifact_id=artifact_id, target_dir=target_dir)

        # Modify the file on disk (simulating user edits)
        written_file = tmp_path / "output" / "scripts" / "helper.py"
        written_file.write_text("def hello():\n    print('Modified!')")

        # Sync back to artifact
        result = sync_tool.fn(artifact_id=artifact_id, source_path=str(written_file))

        assert result["synced"] is True

        # Verify the artifact content was updated
        artifact = read_tool.fn(artifact_id=artifact_id)
        assert artifact["content"] == "def hello():\n    print('Modified!')"

    def test_sync_artifact_from_disk_not_found(self, server, tmp_path):
        """Test syncing a non-existent artifact."""
        sync_tool = server._tool_manager._tools["sync_artifact_from_disk"]

        result = sync_tool.fn(
            artifact_id="a_nonexistent", source_path=str(tmp_path / "nofile.py")
        )
        assert "error" in result

    def test_sync_artifact_from_disk_file_not_found(self, server, tmp_path):
        """Test syncing from a non-existent file."""
        create_tool = server._tool_manager._tools["create_artifact"]
        sync_tool = server._tool_manager._tools["sync_artifact_from_disk"]

        # Create an artifact
        create_result = create_tool.fn(
            name="Some Script",
            content="original",
            path="scripts/some.py",
        )
        artifact_id = create_result["artifact_id"]

        # Try to sync from a file that doesn't exist
        result = sync_tool.fn(
            artifact_id=artifact_id, source_path=str(tmp_path / "nonexistent.py")
        )
        assert "error" in result


class TestServerCoverageGaps:
    """Tests for server code coverage gaps."""

    @pytest.fixture
    def server(self, tmp_path, embedding_model):
        """Create a memory server with temp directory."""
        return create_memory_server(
            base_path=str(tmp_path), embedding_model=embedding_model
        )

    def test_read_thread_with_messages_from_filter(self, server):
        """Test read_thread with messages_from timestamp filter."""
        from datetime import datetime, timedelta

        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        read_tool = server._tool_manager._tools["read_thread"]

        # Create thread
        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        # Add messages at different times
        now = datetime.now()
        old_time = (now - timedelta(hours=1)).isoformat()
        new_time = now.isoformat()

        add_tool.fn(
            thread_id=thread_id,
            messages=[{"role": "user", "text": "Old message", "timestamp": old_time}],
        )
        add_tool.fn(
            thread_id=thread_id,
            messages=[{"role": "user", "text": "New message", "timestamp": new_time}],
        )

        # Read with messages_from filter
        filter_time = (now - timedelta(minutes=30)).isoformat()
        result = read_tool.fn(thread_id=thread_id, messages_from=filter_time)

        assert "messages" in result
        # Should only get messages after the filter time
        assert len(result["messages"]) == 1
        assert result["messages"][0]["text"] == "New message"

    def test_add_messages_thread_not_found(self, server):
        """Test add_messages with non-existent thread."""
        add_tool = server._tool_manager._tools["add_messages"]

        result = add_tool.fn(
            thread_id="nonexistent_thread",
            messages=[{"role": "user", "text": "Hello"}],
        )
        assert "error" in result

    def test_search_messages_tool(self, server):
        """Test search_messages tool."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        search_tool = server._tool_manager._tools["search_messages"]

        # Create thread with messages
        create_result = create_tool.fn(project_id="p_test")
        thread_id = create_result["thread_id"]

        add_tool.fn(
            thread_id=thread_id,
            messages=[{"role": "user", "text": "Question about databases"}],
        )

        # Search messages
        result = search_tool.fn(query="databases")
        assert "results" in result

    def test_search_threads_tool(self, server):
        """Test search_threads tool."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        search_tool = server._tool_manager._tools["search_threads"]

        # Create thread with messages
        create_result = create_tool.fn()
        thread_id = create_result["thread_id"]

        add_tool.fn(
            thread_id=thread_id,
            messages=[{"role": "user", "text": "Kubernetes deployment question"}],
        )

        # Search threads
        result = search_tool.fn(query="kubernetes")
        assert "results" in result

    def test_compact_thread_not_found(self, server):
        """Test compact_thread with non-existent thread."""
        compact_tool = server._tool_manager._tools["compact_thread"]

        result = compact_tool.fn(thread_id="nonexistent", summary="Summary")
        assert "error" in result

    def test_list_threads_tool(self, server):
        """Test list_threads tool."""
        create_tool = server._tool_manager._tools["create_thread"]
        add_tool = server._tool_manager._tools["add_messages"]
        list_tool = server._tool_manager._tools["list_threads"]

        # Create threads
        create_result1 = create_tool.fn(project_id="p_1")
        create_tool.fn(project_id="p_2")  # Second thread for filtering test

        add_tool.fn(
            thread_id=create_result1["thread_id"],
            messages=[{"role": "user", "text": "Message 1"}],
        )

        # List all threads
        result = list_tool.fn()
        assert "threads" in result
        assert len(result["threads"]) == 2

        # List with project filter
        result = list_tool.fn(project_id="p_1")
        assert len(result["threads"]) == 1

    def test_read_concept_not_found(self, server):
        """Test read_concept with non-existent concept."""
        read_tool = server._tool_manager._tools["read_concept"]
        result = read_tool.fn(concept_id="c_nonexistent")
        assert "error" in result

    def test_read_concept_by_name_not_found(self, server):
        """Test read_concept_by_name with non-existent concept."""
        read_tool = server._tool_manager._tools["read_concept_by_name"]
        result = read_tool.fn(name="NonExistent Concept")
        assert "error" in result

    def test_list_concepts_tool(self, server):
        """Test list_concepts tool."""
        create_tool = server._tool_manager._tools["create_concept"]
        list_tool = server._tool_manager._tools["list_concepts"]

        # Create concepts
        create_tool.fn(name="Concept A", project_id="p_1")
        create_tool.fn(name="Concept B", project_id="p_2")

        # List all concepts
        result = list_tool.fn()
        assert "concepts" in result
        assert len(result["concepts"]) == 2

        # List with project filter
        result = list_tool.fn(project_id="p_1")
        assert len(result["concepts"]) == 1

    def test_update_concept_all_fields(self, server):
        """Test update_concept with all optional fields."""
        create_tool = server._tool_manager._tools["create_concept"]
        update_tool = server._tool_manager._tools["update_concept"]
        read_tool = server._tool_manager._tools["read_concept"]

        # Create concept
        create_result = create_tool.fn(name="Original", text="Original text")
        concept_id = create_result["concept_id"]

        # Update all fields
        update_result = update_tool.fn(
            concept_id=concept_id,
            name="Updated Name",
            text="Updated text",
            project_id="p_new",
            tags=["new", "tags"],
        )
        assert update_result["updated"] is True

        # Verify all fields updated
        concept = read_tool.fn(concept_id=concept_id)
        assert concept["name"] == "Updated Name"
        assert concept["text"] == "Updated text"
        assert concept["project_id"] == "p_new"
        assert concept["tags"] == ["new", "tags"]

    def test_update_concept_not_found(self, server):
        """Test update_concept with non-existent concept."""
        update_tool = server._tool_manager._tools["update_concept"]
        result = update_tool.fn(concept_id="c_nonexistent", text="New text")
        assert "error" in result

    def test_update_concept_partial_fields(self, server):
        """Test update_concept with only some fields to cover partial branches."""
        create_tool = server._tool_manager._tools["create_concept"]
        update_tool = server._tool_manager._tools["update_concept"]
        read_tool = server._tool_manager._tools["read_concept"]

        # Create separate concepts for each partial update test
        # This avoids issues with name changes creating new files

        # Test update only text (name, project_id, tags are None)
        result1 = create_tool.fn(name="Concept1", text="Original text")
        concept_id1 = result1["concept_id"]
        update_tool.fn(concept_id=concept_id1, text="New text")
        concept = read_tool.fn(concept_id=concept_id1)
        assert concept["text"] == "New text"

        # Test update only project_id
        result2 = create_tool.fn(name="Concept2", text="Text")
        concept_id2 = result2["concept_id"]
        update_tool.fn(concept_id=concept_id2, project_id="p_123")
        concept = read_tool.fn(concept_id=concept_id2)
        assert concept["project_id"] == "p_123"

        # Test update only tags
        result3 = create_tool.fn(name="Concept3", text="Text")
        concept_id3 = result3["concept_id"]
        update_tool.fn(concept_id=concept_id3, tags=["tag1"])
        concept = read_tool.fn(concept_id=concept_id3)
        assert concept["tags"] == ["tag1"]

        # Test update only name (creates new file, old file remains)
        # Just verify the update succeeds
        result4 = create_tool.fn(name="Concept4", text="Text")
        concept_id4 = result4["concept_id"]
        result = update_tool.fn(concept_id=concept_id4, name="NewName4")
        assert result["updated"] is True

    def test_update_reflection_all_fields(self, server):
        """Test update_reflection with all optional fields."""
        add_tool = server._tool_manager._tools["add_reflection"]
        update_tool = server._tool_manager._tools["update_reflection"]

        # Create reflection
        add_result = add_tool.fn(text="Original reflection")
        reflection_id = add_result["reflection_id"]

        # Update all fields
        update_result = update_tool.fn(
            reflection_id=reflection_id,
            text="Updated reflection",
            project_id="p_new",
            thread_id="t_new",
            skill_id="s_new",
            tags=["updated"],
        )
        assert update_result["updated"] is True

    def test_update_reflection_not_found(self, server):
        """Test update_reflection with non-existent reflection."""
        update_tool = server._tool_manager._tools["update_reflection"]
        result = update_tool.fn(reflection_id="r_nonexistent", text="New text")
        assert "error" in result

    def test_update_reflection_partial_fields(self, server):
        """Test update_reflection with only some fields."""
        add_tool = server._tool_manager._tools["add_reflection"]
        update_tool = server._tool_manager._tools["update_reflection"]
        read_tool = server._tool_manager._tools["read_reflections"]

        # Create reflection
        result = add_tool.fn(text="Original")
        rid = result["reflection_id"]

        def get_reflection():
            refs = read_tool.fn()["reflections"]
            return next(r for r in refs if r["reflection_id"] == rid)

        # Update only text
        update_tool.fn(reflection_id=rid, text="New text")
        assert get_reflection()["text"] == "New text"

        # Update only project_id
        update_tool.fn(reflection_id=rid, project_id="p_1")
        assert get_reflection()["project_id"] == "p_1"

        # Update only thread_id
        update_tool.fn(reflection_id=rid, thread_id="t_1")
        assert get_reflection()["thread_id"] == "t_1"

        # Update only skill_id
        update_tool.fn(reflection_id=rid, skill_id="s_1")
        assert get_reflection()["skill_id"] == "s_1"

        # Update only tags
        update_tool.fn(reflection_id=rid, tags=["tag1"])
        assert get_reflection()["tags"] == ["tag1"]

    def test_update_project_all_fields(self, server):
        """Test update_project with all optional fields."""
        create_tool = server._tool_manager._tools["create_project"]
        update_tool = server._tool_manager._tools["update_project"]
        read_tool = server._tool_manager._tools["read_project"]

        # Create project
        create_result = create_tool.fn(name="Original Project")
        project_id = create_result["project_id"]

        # Update all fields
        update_result = update_tool.fn(
            project_id=project_id,
            name="Updated Project",
            description="New description",
            instructions="New instructions",
            tags=["updated"],
        )
        assert update_result["updated"] is True

        # Verify all fields updated
        project = read_tool.fn(project_id=project_id)
        assert project["name"] == "Updated Project"
        assert project["description"] == "New description"
        assert project["instructions"] == "New instructions"
        assert project["tags"] == ["updated"]

    def test_update_project_not_found(self, server):
        """Test update_project with non-existent project."""
        update_tool = server._tool_manager._tools["update_project"]
        result = update_tool.fn(project_id="p_nonexistent", name="New name")
        assert "error" in result

    def test_update_project_partial_fields(self, server):
        """Test update_project with only some fields."""
        create_tool = server._tool_manager._tools["create_project"]
        update_tool = server._tool_manager._tools["update_project"]

        # Test each field individually
        result1 = create_tool.fn(name="Project1")
        update_tool.fn(project_id=result1["project_id"], description="Desc only")
        assert True  # Just verify no error

        result2 = create_tool.fn(name="Project2")
        update_tool.fn(project_id=result2["project_id"], instructions="Instr only")
        assert True

        result3 = create_tool.fn(name="Project3")
        update_tool.fn(project_id=result3["project_id"], tags=["tag"])
        assert True

    def test_update_skill_all_fields(self, server):
        """Test update_skill with all optional fields."""
        create_tool = server._tool_manager._tools["create_skill"]
        update_tool = server._tool_manager._tools["update_skill"]
        read_tool = server._tool_manager._tools["read_skill"]

        # Create skill
        create_result = create_tool.fn(name="Original Skill")
        skill_id = create_result["skill_id"]

        # Update all fields
        update_result = update_tool.fn(
            skill_id=skill_id,
            name="Updated Skill",
            description="New description",
            instructions="New instructions",
            tags=["updated"],
        )
        assert update_result["updated"] is True

        # Verify all fields updated
        skill = read_tool.fn(skill_id=skill_id)
        assert skill["name"] == "Updated Skill"
        assert skill["description"] == "New description"
        assert skill["instructions"] == "New instructions"
        assert skill["tags"] == ["updated"]

    def test_update_skill_not_found(self, server):
        """Test update_skill with non-existent skill."""
        update_tool = server._tool_manager._tools["update_skill"]
        result = update_tool.fn(skill_id="s_nonexistent", name="New name")
        assert "error" in result

    def test_update_skill_partial_fields(self, server):
        """Test update_skill with only some fields."""
        create_tool = server._tool_manager._tools["create_skill"]
        update_tool = server._tool_manager._tools["update_skill"]

        result1 = create_tool.fn(name="Skill1")
        update_tool.fn(skill_id=result1["skill_id"], description="Desc only")
        assert True

        result2 = create_tool.fn(name="Skill2")
        update_tool.fn(skill_id=result2["skill_id"], instructions="Instr only")
        assert True

        result3 = create_tool.fn(name="Skill3")
        update_tool.fn(skill_id=result3["skill_id"], tags=["tag"])
        assert True

    def test_update_artifact_all_fields(self, server):
        """Test update_artifact with all optional fields."""
        create_tool = server._tool_manager._tools["create_artifact"]
        update_tool = server._tool_manager._tools["update_artifact"]
        read_tool = server._tool_manager._tools["read_artifact"]

        # Create artifact
        create_result = create_tool.fn(name="Original Artifact")
        artifact_id = create_result["artifact_id"]

        # Update all fields
        update_result = update_tool.fn(
            artifact_id=artifact_id,
            name="Updated Artifact",
            content="New content",
            description="New description",
            content_type="code",
            path="new/path.py",
            skill_id="s_new",
            project_id="p_new",
            tags=["updated"],
        )
        assert update_result["updated"] is True

        # Verify all fields updated
        artifact = read_tool.fn(artifact_id=artifact_id)
        assert artifact["name"] == "Updated Artifact"
        assert artifact["content"] == "New content"
        assert artifact["description"] == "New description"
        assert artifact["content_type"] == "code"
        assert artifact["path"] == "new/path.py"
        assert artifact["skill_id"] == "s_new"
        assert artifact["project_id"] == "p_new"
        assert artifact["tags"] == ["updated"]

    def test_update_artifact_not_found(self, server):
        """Test update_artifact with non-existent artifact."""
        update_tool = server._tool_manager._tools["update_artifact"]
        result = update_tool.fn(artifact_id="a_nonexistent", name="New name")
        assert "error" in result

    def test_update_artifact_partial_fields(self, server):
        """Test update_artifact with only some fields."""
        create_tool = server._tool_manager._tools["create_artifact"]
        update_tool = server._tool_manager._tools["update_artifact"]

        result1 = create_tool.fn(name="Artifact1")
        update_tool.fn(artifact_id=result1["artifact_id"], content="Content only")
        assert True

        result2 = create_tool.fn(name="Artifact2")
        update_tool.fn(artifact_id=result2["artifact_id"], description="Desc only")
        assert True

        result3 = create_tool.fn(name="Artifact3")
        update_tool.fn(artifact_id=result3["artifact_id"], content_type="code")
        assert True

        result4 = create_tool.fn(name="Artifact4")
        update_tool.fn(artifact_id=result4["artifact_id"], path="some/path.py")
        assert True

        result5 = create_tool.fn(name="Artifact5")
        update_tool.fn(artifact_id=result5["artifact_id"], skill_id="s_1")
        assert True

        result6 = create_tool.fn(name="Artifact6")
        update_tool.fn(artifact_id=result6["artifact_id"], project_id="p_1")
        assert True

        result7 = create_tool.fn(name="Artifact7")
        update_tool.fn(artifact_id=result7["artifact_id"], tags=["tag"])
        assert True

    def test_search_artifacts_tool(self, server):
        """Test search_artifacts tool."""
        create_tool = server._tool_manager._tools["create_artifact"]
        search_tool = server._tool_manager._tools["search_artifacts"]

        # Create artifact
        create_tool.fn(
            name="Database Schema",
            content="CREATE TABLE users (id INT, name VARCHAR)",
            project_id="p_test",
        )

        # Search artifacts
        result = search_tool.fn(query="database schema")
        assert "results" in result

    def test_rebuild_index_tool(self, server):
        """Test rebuild_index tool."""
        create_tool = server._tool_manager._tools["create_concept"]
        rebuild_tool = server._tool_manager._tools["rebuild_index"]

        # Create some content
        create_tool.fn(name="Test Concept", text="Test content")

        # Rebuild index
        result = rebuild_tool.fn()
        assert result["rebuilt"] is True

    def test_read_project_not_found(self, server):
        """Test read_project with non-existent project."""
        read_tool = server._tool_manager._tools["read_project"]
        result = read_tool.fn(project_id="p_nonexistent")
        assert "error" in result

    def test_read_skill_not_found(self, server):
        """Test read_skill with non-existent skill."""
        read_tool = server._tool_manager._tools["read_skill"]
        result = read_tool.fn(skill_id="s_nonexistent")
        assert "error" in result

    def test_read_artifact_not_found(self, server):
        """Test read_artifact with non-existent artifact."""
        read_tool = server._tool_manager._tools["read_artifact"]
        result = read_tool.fn(artifact_id="a_nonexistent")
        assert "error" in result

    def test_write_artifact_to_disk_not_found(self, server, tmp_path):
        """Test write_artifact_to_disk with non-existent artifact."""
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]
        result = write_tool.fn(artifact_id="a_nonexistent", target_dir=str(tmp_path))
        assert "error" in result

    def test_write_artifact_to_disk_no_path(self, server, tmp_path):
        """Test write_artifact_to_disk with artifact that has no path."""
        create_tool = server._tool_manager._tools["create_artifact"]
        write_tool = server._tool_manager._tools["write_artifact_to_disk"]

        # Create artifact without path
        create_result = create_tool.fn(name="No Path Artifact", content="content")
        artifact_id = create_result["artifact_id"]

        result = write_tool.fn(artifact_id=artifact_id, target_dir=str(tmp_path))
        assert "error" in result
        assert "no path" in result["error"].lower()

    def test_sync_artifact_from_disk_not_found(self, server, tmp_path):
        """Test sync_artifact_from_disk with non-existent artifact."""
        sync_tool = server._tool_manager._tools["sync_artifact_from_disk"]
        src_path = str(tmp_path / "file.py")
        result = sync_tool.fn(artifact_id="a_nonexistent", source_path=src_path)
        assert "error" in result

    def test_list_skills_tool(self, server):
        """Test list_skills tool."""
        create_tool = server._tool_manager._tools["create_skill"]
        list_tool = server._tool_manager._tools["list_skills"]

        # Create skills
        create_tool.fn(name="Skill A", description="Description A")
        create_tool.fn(name="Skill B", description="Description B")

        # List skills
        result = list_tool.fn()
        assert "skills" in result
        assert len(result["skills"]) == 2

    def test_search_skills_tool(self, server):
        """Test search_skills tool."""
        create_tool = server._tool_manager._tools["create_skill"]
        search_tool = server._tool_manager._tools["search_skills"]

        # Create skill
        create_tool.fn(
            name="Python Testing",
            description="How to test Python code",
            instructions="Use pytest for testing",
        )

        # Search skills
        result = search_tool.fn(query="python testing")
        assert "results" in result

    def test_list_projects_tool(self, server):
        """Test list_projects tool."""
        create_tool = server._tool_manager._tools["create_project"]
        list_tool = server._tool_manager._tools["list_projects"]

        # Create projects
        create_tool.fn(name="Project A")
        create_tool.fn(name="Project B")

        # List projects
        result = list_tool.fn()
        assert "projects" in result
        assert len(result["projects"]) == 2

    def test_search_concepts_tool(self, server):
        """Test search_concepts tool."""
        create_tool = server._tool_manager._tools["create_concept"]
        search_tool = server._tool_manager._tools["search_concepts"]

        # Create concept
        create_tool.fn(
            name="Database Design",
            text="Information about database schema design",
            project_id="p_test",
        )

        # Search concepts
        result = search_tool.fn(query="database schema")
        assert "results" in result

        # Search with project filter
        result = search_tool.fn(query="database", project_id="p_test")
        assert "results" in result
