"""Tests for exception classes."""

import pytest

from mcp_proxy.exceptions import ToolCallAborted


class TestToolCallAborted:
    """Tests for ToolCallAborted exception."""

    def test_tool_call_aborted_creation(self):
        """ToolCallAborted can be created with a reason."""
        exc = ToolCallAborted(reason="Access denied")
        assert exc.reason == "Access denied"

    def test_tool_call_aborted_str(self):
        """ToolCallAborted has readable string representation."""
        exc = ToolCallAborted(reason="Rate limited")
        assert "Rate limited" in str(exc)

    def test_tool_call_aborted_is_exception(self):
        """ToolCallAborted is a proper Exception subclass."""
        exc = ToolCallAborted(reason="Test")
        assert isinstance(exc, Exception)

    def test_tool_call_aborted_with_context(self):
        """ToolCallAborted can include tool context."""
        exc = ToolCallAborted(
            reason="Unauthorized",
            tool_name="search_memory",
            view_name="redis-expert"
        )
        assert exc.tool_name == "search_memory"
        assert exc.view_name == "redis-expert"

