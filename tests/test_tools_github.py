"""Tests for mcp_proxy.tools.github module."""

import pytest

from mcp_proxy.hooks import ToolCallContext
from mcp_proxy.tools.github import (
    ISSUE_FIELDS,
    PR_FIELDS,
    _filter_item,
    filter_github_response,
    github_count_issues,
)


class TestFilterItem:
    """Tests for _filter_item helper function."""

    def test_filter_item_non_dict(self):
        """Non-dict items are returned unchanged."""
        assert _filter_item("string", ISSUE_FIELDS) == "string"
        assert _filter_item(123, ISSUE_FIELDS) == 123
        assert _filter_item(None, ISSUE_FIELDS) is None

    def test_filter_item_keeps_specified_fields(self):
        """Only specified fields are kept."""
        item = {
            "number": 42,
            "title": "Test Issue",
            "extra_field": "should be removed",
            "state": "open",
        }
        result = _filter_item(item, ISSUE_FIELDS)
        assert result == {"number": 42, "title": "Test Issue", "state": "open"}
        assert "extra_field" not in result

    def test_filter_item_extracts_user_login(self):
        """User field is simplified to just login."""
        item = {
            "number": 1,
            "user": {"login": "octocat", "id": 12345, "avatar_url": "..."},
        }
        result = _filter_item(item, ISSUE_FIELDS)
        assert result["user"] == {"login": "octocat"}

    def test_filter_item_extracts_label_names(self):
        """Labels are simplified to just names."""
        item = {
            "number": 1,
            "labels": [
                {"name": "bug", "color": "red", "id": 1},
                {"name": "help wanted", "color": "green", "id": 2},
            ],
        }
        result = _filter_item(item, ISSUE_FIELDS)
        assert result["labels"] == [{"name": "bug"}, {"name": "help wanted"}]

    def test_filter_item_handles_non_dict_labels(self):
        """Labels that are strings pass through."""
        item = {"number": 1, "labels": ["bug", "help wanted"]}
        result = _filter_item(item, ISSUE_FIELDS)
        assert result["labels"] == ["bug", "help wanted"]

    def test_filter_item_extracts_requested_reviewers(self):
        """Requested reviewers are simplified to logins."""
        item = {
            "number": 1,
            "requested_reviewers": [
                {"login": "reviewer1", "id": 100},
                {"login": "reviewer2", "id": 200},
            ],
        }
        result = _filter_item(item, PR_FIELDS)
        assert result["requested_reviewers"] == [
            {"login": "reviewer1"},
            {"login": "reviewer2"},
        ]

    def test_filter_item_extracts_head_base_refs(self):
        """Head and base are simplified to ref and sha."""
        item = {
            "number": 1,
            "head": {"ref": "feature-branch", "sha": "abc123", "label": "..."},
            "base": {"ref": "main", "sha": "def456", "label": "..."},
        }
        result = _filter_item(item, PR_FIELDS)
        assert result["head"] == {"ref": "feature-branch", "sha": "abc123"}
        assert result["base"] == {"ref": "main", "sha": "def456"}


class TestFilterGithubResponse:
    """Tests for filter_github_response hook."""

    @pytest.mark.asyncio
    async def test_filter_list_of_issues(self):
        """List of issues is filtered."""
        ctx = ToolCallContext("view", "list_issues", "github")
        result = [
            {"number": 1, "title": "Issue 1", "extra": "remove"},
            {"number": 2, "title": "Issue 2", "extra": "remove"},
        ]
        hook_result = await filter_github_response(result, {}, ctx)
        assert len(hook_result.result) == 2
        assert hook_result.result[0] == {"number": 1, "title": "Issue 1"}
        assert "extra" not in hook_result.result[0]

    @pytest.mark.asyncio
    async def test_filter_single_issue_dict(self):
        """Single issue dict is filtered."""
        ctx = ToolCallContext("view", "get_issue", "github")
        result = {"number": 42, "title": "Test", "extra": "remove", "state": "open"}
        hook_result = await filter_github_response(result, {}, ctx)
        assert hook_result.result == {"number": 42, "title": "Test", "state": "open"}

    @pytest.mark.asyncio
    async def test_filter_search_result_with_items(self):
        """Search result with items array is filtered."""
        ctx = ToolCallContext("view", "search_issues", "github")
        result = {
            "total_count": 100,
            "items": [{"number": 1, "title": "Found", "extra": "remove"}],
        }
        hook_result = await filter_github_response(result, {}, ctx)
        assert hook_result.result["total_count"] == 100
        assert hook_result.result["items"] == [{"number": 1, "title": "Found"}]

    @pytest.mark.asyncio
    async def test_filter_uses_pr_fields_for_pull_requests(self):
        """PR-related tools use PR_FIELDS."""
        ctx = ToolCallContext("view", "list_pull_requests", "github")
        result = [{"number": 1, "draft": True, "mergeable": True, "extra": "remove"}]
        hook_result = await filter_github_response(result, {}, ctx)
        assert hook_result.result[0]["draft"] is True
        assert hook_result.result[0]["mergeable"] is True

    @pytest.mark.asyncio
    async def test_filter_passes_through_non_dict_non_list(self):
        """Non-dict/list results pass through unchanged."""
        ctx = ToolCallContext("view", "some_tool", "github")
        hook_result = await filter_github_response("string result", {}, ctx)
        assert hook_result.result == "string result"


class TestGithubCountIssues:
    """Tests for github_count_issues custom tool."""

    @pytest.mark.asyncio
    async def test_count_issues_basic(self):
        """Basic count returns total_count from search."""
        from unittest.mock import AsyncMock, MagicMock

        mock_ctx = MagicMock()
        mock_ctx.call_tool = AsyncMock(return_value={"total_count": 42, "items": []})

        result = await github_count_issues(mock_ctx, "redis", "redis-py")

        mock_ctx.call_tool.assert_called_once()
        call_args = mock_ctx.call_tool.call_args
        assert call_args[0][0] == "github.search_issues"
        assert "repo:redis/redis-py" in call_args[1]["query"]
        assert result["count"] == 42
        assert result["type"] == "issue"
        assert result["state"] == "open"

    @pytest.mark.asyncio
    async def test_count_issues_with_all_filters(self):
        """Count with label and author filters."""
        from unittest.mock import AsyncMock, MagicMock

        mock_ctx = MagicMock()
        mock_ctx.call_tool = AsyncMock(return_value={"total_count": 5, "items": []})

        result = await github_count_issues(
            mock_ctx,
            "redis",
            "redis-py",
            state="closed",
            type="pr",
            label="bug",
            author="octocat",
        )

        call_args = mock_ctx.call_tool.call_args
        query = call_args[1]["query"]
        assert "is:pr" in query
        assert "is:closed" in query
        assert "label:bug" in query
        assert "author:octocat" in query
        assert result["type"] == "pr"
        assert result["state"] == "closed"

    @pytest.mark.asyncio
    async def test_count_issues_state_all_omits_state_filter(self):
        """state='all' omits the is:state filter."""
        from unittest.mock import AsyncMock, MagicMock

        mock_ctx = MagicMock()
        mock_ctx.call_tool = AsyncMock(return_value={"total_count": 10, "items": []})

        await github_count_issues(mock_ctx, "redis", "redis-py", state="all")

        call_args = mock_ctx.call_tool.call_args
        query = call_args[1]["query"]
        assert "is:open" not in query
        assert "is:closed" not in query

    @pytest.mark.asyncio
    async def test_count_issues_non_dict_result(self):
        """Non-dict result returns count 0."""
        from unittest.mock import AsyncMock, MagicMock

        mock_ctx = MagicMock()
        mock_ctx.call_tool = AsyncMock(return_value="unexpected string")

        result = await github_count_issues(mock_ctx, "redis", "redis-py")

        assert result["count"] == 0
