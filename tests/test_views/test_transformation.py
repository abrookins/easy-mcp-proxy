"""Tests for tool transformation (rename/description override)."""

from mcp_proxy.models import ToolConfig, ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolTransformation:
    """Tests for tool transformation (rename/description override)."""

    def test_transform_tool_rename(self):
        """_transform_tool should rename a tool."""
        view = ToolView("test", ToolViewConfig())

        # Create a mock tool
        class MockTool:
            name = "original_name"
            description = "Original description"

        config = ToolConfig(name="new_name")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "new_name"

    def test_transform_tool_description_override(self):
        """_transform_tool should override description with {original} placeholder."""
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "tool"
            description = "Original description"

        config = ToolConfig(description="New prefix. {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.description == "New prefix. Original description"

    def test_transform_tool_both_name_and_description(self):
        """_transform_tool should handle both name and description."""
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "old"
            description = "Old desc"

        config = ToolConfig(name="new", description="Custom: {original}")
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "new"
        assert transformed.description == "Custom: Old desc"

    def test_transform_tool_preserves_original_when_no_overrides(self):
        """_transform_tool should preserve original when no overrides given."""
        view = ToolView("test", ToolViewConfig())

        class MockTool:
            name = "original"
            description = "Original desc"

        config = ToolConfig()  # No overrides
        transformed = view._transform_tool(MockTool(), config)

        assert transformed.name == "original"
        assert transformed.description == "Original desc"

