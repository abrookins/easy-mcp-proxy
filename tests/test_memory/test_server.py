"""Tests for mcp_memory MCP server."""

import pytest
from datetime import datetime

from mcp_memory.models import MemoryConfig
from mcp_memory.server import create_memory_server
from mcp_memory.storage import MemoryStorage


class TestMemoryServer:
    """Tests for the MCP Memory server."""

    @pytest.fixture
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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
            "rebuild_index",
        ]
        for tool_name in expected_tools:
            assert tool_name in tools, f"Missing tool: {tool_name}"

    @pytest.fixture
    def storage(self, tmp_path):
        """Create storage for direct verification."""
        config = MemoryConfig(base_path=str(tmp_path))
        return MemoryStorage(config)


class TestThreadTools:
    """Tests for thread-related tools."""

    @pytest.fixture
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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

        compact_result = compact_tool.fn(
            thread_id=thread_id, summary="User said hello"
        )
        assert compact_result["compacted"] is True

        read_result = read_tool.fn(thread_id=thread_id)
        assert read_result["summary"] == "User said hello"
        assert read_result["messages"] == []


class TestConceptTools:
    """Tests for concept-related tools."""

    @pytest.fixture
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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
            instructions="Step 1: Create branch\nStep 2: Commit\nStep 3: Push\nStep 4: PR",
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
            assert "instructions" not in skill, "list_skills should not include instructions"

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
            instructions="Step 1: Import pytest\nStep 2: Write test functions\nStep 3: Run with pytest",
            description="Complete guide to Python testing",
        )
        assert update_result["updated"] is True

        # Verify the update
        skill = read_tool.fn(skill_id=skill_id)
        assert "Step 3: Run with pytest" in skill["instructions"]
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


class TestProjectTools:
    """Tests for project-related tools."""

    @pytest.fixture
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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
    def server(self, tmp_path):
        """Create a memory server with temp directory."""
        return create_memory_server(base_path=str(tmp_path))

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
        matching = [r for r in reflections["reflections"] if r["reflection_id"] == reflection_id]
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

