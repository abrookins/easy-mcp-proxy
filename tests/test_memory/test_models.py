"""Tests for mcp_memory models."""

import re
from datetime import datetime

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


class TestGenerateId:
    """Tests for ID generation."""

    # ULID format: 26 chars, Crockford Base32 (0-9, A-Z excluding I, L, O, U)
    ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

    def test_generate_id_with_prefix(self):
        """Test that IDs are generated with the correct prefix and ULID format."""
        id1 = generate_id("t")
        assert id1.startswith("t_")
        # prefix (1) + underscore (1) + ULID (26) = 28 chars
        assert len(id1) == 28
        ulid_part = id1[2:]
        assert self.ULID_PATTERN.match(ulid_part), f"'{ulid_part}' is not a valid ULID"

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
        assert concept.parent_path is None
        assert concept.links == []

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

    def test_concept_hierarchy(self):
        """Test concept with parent_path for hierarchy."""
        concept = Concept(
            name="Preferences",
            parent_path="Andrew Brookins",
            text="User preferences.",
        )
        assert concept.name == "Preferences"
        assert concept.parent_path == "Andrew Brookins"
        assert concept.full_path == "Andrew Brookins/Preferences"

    def test_concept_deep_hierarchy(self):
        """Test concept with deep nesting."""
        concept = Concept(
            name="Lane",
            parent_path="Lane Harker/Characters",
            text="Main character.",
        )
        assert concept.full_path == "Lane Harker/Characters/Lane"

    def test_concept_full_path_no_parent(self):
        """Test full_path for root-level concept."""
        concept = Concept(name="Root Concept")
        assert concept.full_path == "Root Concept"

    def test_concept_with_links(self):
        """Test concept with cross-references."""
        concept = Concept(
            name="Nose",
            parent_path="Anatomy/Face",
            links=["Respiratory System", "Sensory Organs"],
        )
        assert concept.links == ["Respiratory System", "Sensory Organs"]
        assert concept.full_path == "Anatomy/Face/Nose"


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


class TestArtifact:
    """Tests for Artifact model."""

    def test_artifact_creation(self):
        """Test creating an artifact with minimal fields."""
        artifact = Artifact(name="API Design Doc")
        assert artifact.artifact_id.startswith("a_")
        assert artifact.name == "API Design Doc"
        assert artifact.description == ""
        assert artifact.content_type == "markdown"
        assert artifact.project_id is None
        assert artifact.originating_thread_id is None
        assert artifact.content == ""
        assert artifact.tags == []

    def test_artifact_with_full_content(self):
        """Test artifact with all fields populated."""
        artifact = Artifact(
            name="System Architecture",
            description="High-level system design document",
            content_type="markdown",
            project_id="p_123",
            originating_thread_id="t_456",
            tags=["architecture", "design"],
            content="# Architecture\n\nThis is the system architecture.",
        )
        assert artifact.name == "System Architecture"
        assert artifact.description == "High-level system design document"
        assert artifact.content_type == "markdown"
        assert artifact.project_id == "p_123"
        assert artifact.originating_thread_id == "t_456"
        assert "architecture" in artifact.tags
        assert "# Architecture" in artifact.content

    def test_artifact_content_types(self):
        """Test artifact with different content types."""
        code_artifact = Artifact(
            name="utils.py",
            content_type="code",
            content="def hello():\n    print('Hello')",
        )
        assert code_artifact.content_type == "code"

        json_artifact = Artifact(
            name="config.json",
            content_type="json",
            content='{"key": "value"}',
        )
        assert json_artifact.content_type == "json"

    def test_artifact_with_path(self):
        """Test artifact with path field for file-based artifacts."""
        artifact = Artifact(
            name="Migration Helper",
            content_type="code",
            path="database-migration/migration_helper.py",
            content="def migrate():\n    pass",
        )
        assert artifact.path == "database-migration/migration_helper.py"

    def test_artifact_path_defaults_to_none(self):
        """Test that path is optional and defaults to None."""
        artifact = Artifact(name="Some Doc")
        assert artifact.path is None

    def test_artifact_with_skill_id(self):
        """Test artifact linked to a skill."""
        artifact = Artifact(
            name="Helper Script",
            skill_id="s_abc123",
            path="scripts/helper.py",
            content="# helper code",
        )
        assert artifact.skill_id == "s_abc123"

    def test_artifact_skill_id_defaults_to_none(self):
        """Test that skill_id is optional and defaults to None."""
        artifact = Artifact(name="Standalone Doc")
        assert artifact.skill_id is None


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
        assert config.artifacts_dir == "Artifacts"

    def test_custom_config(self):
        """Test custom configuration."""
        config = MemoryConfig(base_path="/data/memory", threads_dir="Conversations")
        assert config.base_path == "/data/memory"
        assert config.threads_dir == "Conversations"
