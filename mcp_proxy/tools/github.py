"""GitHub efficiency tools and hooks.

Provides:
- Field filtering hook to reduce response sizes
- Count-only tool for getting issue/PR counts without full data
"""

from typing import Any

from mcp_proxy.custom_tools import ProxyContext, custom_tool
from mcp_proxy.hooks import HookResult, ToolCallContext

# Fields to keep for issues (minimal set for triage)
ISSUE_FIELDS = {
    "number",
    "title",
    "user",
    "labels",
    "created_at",
    "updated_at",
    "state",
    "html_url",
    "body",  # Often useful for context
}

# Additional fields for PRs
PR_FIELDS = ISSUE_FIELDS | {
    "draft",
    "requested_reviewers",
    "head",
    "base",
    "mergeable",
    "merged",
}


def _filter_item(item: dict, fields: set) -> dict:
    """Filter a single item to only include specified fields."""
    if not isinstance(item, dict):
        return item

    filtered = {}
    for key in fields:
        if key in item:
            value = item[key]
            # Handle nested objects - extract key info
            if key == "user" and isinstance(value, dict):
                filtered[key] = {"login": value.get("login")}
            elif key == "labels" and isinstance(value, list):
                filtered[key] = [
                    {"name": lbl.get("name")} if isinstance(lbl, dict) else lbl
                    for lbl in value
                ]
            elif key == "requested_reviewers" and isinstance(value, list):
                filtered[key] = [
                    {"login": r.get("login")} if isinstance(r, dict) else r
                    for r in value
                ]
            elif key in ("head", "base") and isinstance(value, dict):
                filtered[key] = {
                    "ref": value.get("ref"),
                    "sha": value.get("sha"),
                }
            else:
                filtered[key] = value
    return filtered


async def filter_github_response(
    result: Any, args: dict, context: ToolCallContext
) -> HookResult:
    """Post-call hook to filter GitHub responses to essential fields.

    Reduces response sizes significantly for triage workflows.
    Configure in your view:

        tool_views:
          github_filtered:
            hooks:
              post_call: mcp_proxy.tools.github.filter_github_response
    """
    # Determine if this is a PR-related tool
    tool_name = context.tool_name.lower()
    is_pr = "pull" in tool_name or "pr" in tool_name
    fields = PR_FIELDS if is_pr else ISSUE_FIELDS

    # Handle different result structures
    if isinstance(result, list):
        filtered = [_filter_item(item, fields) for item in result]
        return HookResult(result=filtered)

    if isinstance(result, dict):
        # Could be a single issue/PR or a search result with items
        if "items" in result:
            result["items"] = [_filter_item(item, fields) for item in result["items"]]
            # Keep total_count if present
            return HookResult(result=result)
        # Single item
        return HookResult(result=_filter_item(result, fields))

    # Pass through unchanged for other types
    return HookResult(result=result)


@custom_tool(
    name="github_count_issues",
    description="""Count issues or PRs in a repository without fetching all data.

Uses the GitHub search API which returns total_count efficiently.
Much faster than listing all issues when you just need a count.

Examples:
- Count open issues: github_count_issues(owner="redis", repo="redis-py", state="open")
- Count open PRs: github_count_issues(owner="redis", repo="redis-py", type="pr")
- Count by label: github_count_issues(owner="...", repo="...", label="bug")""",
)
async def github_count_issues(
    ctx: ProxyContext,
    owner: str,
    repo: str,
    state: str = "open",
    type: str = "issue",
    label: str | None = None,
    author: str | None = None,
) -> dict:
    """Count issues or PRs without fetching full data.

    Args:
        ctx: Proxy context for calling upstream tools
        owner: Repository owner
        repo: Repository name
        state: Filter by state - open, closed, all (default: open)
        type: Type to count - issue or pr (default: issue)
        label: Optional label to filter by
        author: Optional author username to filter by

    Returns:
        Dict with count and query used
    """
    # Build search query
    parts = [f"repo:{owner}/{repo}", f"is:{type}"]

    if state != "all":
        parts.append(f"is:{state}")
    if label:
        parts.append(f"label:{label}")
    if author:
        parts.append(f"author:{author}")

    query = " ".join(parts)

    # Call search with minimal results (we only want total_count)
    result = await ctx.call_tool("github.search_issues", query=query, per_page=1)

    # Extract count from result
    if isinstance(result, dict):
        count = result.get("total_count", 0)
    else:
        count = 0

    return {
        "count": count,
        "query": query,
        "type": type,
        "state": state,
    }
