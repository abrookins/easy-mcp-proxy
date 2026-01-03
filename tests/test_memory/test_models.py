"""Tests for mcp_memory models."""

import pytest
from datetime import datetime

from mcp_memory.models import (
    Concept,
    MemoryConfig,
    Message,
    Project,
    Reflection,
    Skill,
    Thread,
    generate_id,
)


class TestGenerateId:
    """Tests for ID generation."""

    def test_generate_id_with_prefix(self):
        """Test that IDs are generated with the correct prefix."""
        id1 = generate_id("t")
        assert id1.startswith("t_")
        assert len(id1) == 14  # prefix + underscore + 12 hex chars

    def test_generate_id_unique(self):
        """Test that generated IDs are unique."""
        ids = [generate_id("c") for _ in range(100)]
        assert len(set(ids)) == 100


class TestMessage:
    """Tests for Message model."""

    def test_message_creation(self):
        """Test creating a message."""
        msg = Message(role="user", text="Hello world")
        assert msg.role == "user"
        assert msg.text == "Hello world"
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_timestamp(self):
        """Test creating a message with custom timestamp."""
        ts = datetime(2024, 1, 1, 12, 0, 0)
        msg = Message(role="assistant", text="Hi", timestamp=ts)
        assert msg.timestamp == ts


class TestThread:
    """Tests for Thread model."""

    def test_thread_creation(self):
        """Test creating a thread."""
        thread = Thread()
        assert thread.thread_id.startswith("t_")
        assert thread.project_id is None
        assert thread.messages == []
        assert thread.summary is None

    def test_thread_with_project(self):
        """Test creating a thread with project association."""
        thread = Thread(project_id="p_123")
        assert thread.project_id == "p_123"

    def test_thread_with_messages(self):
        """Test thread with messages."""
        thread = Thread()
        thread.messages.append(Message(role="user", text="Hello"))
        thread.messages.append(Message(role="assistant", text="Hi"))
        assert len(thread.messages) == 2


class TestConcept:
    """Tests for Concept model."""

    def test_concept_creation(self):
        """Test creating a concept."""
        concept = Concept(name="Test Concept")
        assert concept.concept_id.startswith("c_")
        assert concept.name == "Test Concept"
        assert concept.text == ""
        assert concept.tags == []

    def test_concept_with_content(self):
        """Test concept with full content."""
        concept = Concept(
            name="Lane Harker",
            text="A character in the story.",
            project_id="p_123",
            tags=["character", "main"],
        )
        assert concept.name == "Lane Harker"
        assert concept.text == "A character in the story."
        assert concept.project_id == "p_123"
        assert "character" in concept.tags


class TestProject:
    """Tests for Project model."""

    def test_project_creation(self):
        """Test creating a project."""
        project = Project(name="Island Story")
        assert project.project_id.startswith("p_")
        assert project.name == "Island Story"
        assert project.description == ""
        assert project.instructions == ""


class TestSkill:
    """Tests for Skill model."""

    def test_skill_creation(self):
        """Test creating a skill."""
        skill = Skill(name="Code Review", description="How to review code")
        assert skill.skill_id.startswith("s_")
        assert skill.name == "Code Review"
        assert skill.description == "How to review code"


class TestReflection:
    """Tests for Reflection model."""

    def test_reflection_creation(self):
        """Test creating a reflection."""
        reflection = Reflection(text="Learned something new")
        assert reflection.reflection_id.startswith("r_")
        assert reflection.text == "Learned something new"
        assert reflection.project_id is None
        assert reflection.skill_id is None

    def test_reflection_with_associations(self):
        """Test reflection with project and skill."""
        reflection = Reflection(
            text="Improved my skills",
            project_id="p_123",
            skill_id="s_456",
            thread_id="t_789",
        )
        assert reflection.project_id == "p_123"
        assert reflection.skill_id == "s_456"
        assert reflection.thread_id == "t_789"


class TestMemoryConfig:
    """Tests for MemoryConfig model."""

    def test_default_config(self):
        """Test default configuration."""
        config = MemoryConfig()
        assert config.base_path == "."
        assert config.threads_dir == "Threads"
        assert config.concepts_dir == "Concepts"
        assert config.projects_dir == "Projects"
        assert config.skills_dir == "Skills"
        assert config.reflections_dir == "Reflections"

    def test_custom_config(self):
        """Test custom configuration."""
        config = MemoryConfig(base_path="/data/memory", threads_dir="Conversations")
        assert config.base_path == "/data/memory"
        assert config.threads_dir == "Conversations"

