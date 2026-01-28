# Use Cases

This guide explores Easy MCP Proxy features through the problems they solve. Find your challenge, see the solution.

## Table of Contents

- [Too Many Tools Overwhelming the LLM](#too-many-tools-overwhelming-the-llm)
- [Generic Tool Names Are Confusing](#generic-tool-names-are-confusing)
- [Exposing Implementation Details](#exposing-implementation-details)
- [Need to Search Multiple Sources](#need-to-search-multiple-sources)
- [Different Users Need Different Tools](#different-users-need-different-tools)
- [Want to Log or Audit Tool Calls](#want-to-log-or-audit-tool-calls)
- [Need Custom Business Logic](#need-custom-business-logic)
- [Large Tool Outputs Waste Context](#large-tool-outputs-waste-context) *(Recursive Language Model pattern)*

---

## Too Many Tools Overwhelming the LLM

### The Problem

You've connected 5 MCP servers with 50+ tools total. The LLM struggles to pick the right tool, often choosing poorly or getting confused by similar-sounding options.

### The Solution: Search Mode

Instead of exposing all tools directly, use search mode to expose just two meta-tools:

```yaml
tool_views:
  everything:
    description: "All tools via intelligent search"
    exposure_mode: search
    include_all: true
```

**Result**: The LLM gets:
- `everything_search_tools(query)` — Describe what you need, get matching tools
- `everything_call_tool(tool_name, arguments)` — Call the tool you found

The LLM searches first ("I need to read a file"), finds `filesystem.read_file`, then calls it. Much cleaner than scanning 50 tool descriptions.

### Variation: Search Per Server

For better organization when you have many servers:

```yaml
tool_views:
  organized:
    exposure_mode: search_per_server
    include_all: true
```

**Result**: Each server gets its own search/call pair:
- `filesystem_search_tools`, `filesystem_call_tool`
- `github_search_tools`, `github_call_tool`
- etc.

---

## Generic Tool Names Are Confusing

### The Problem

You have `read_file` from a filesystem server, but it's actually reading from your "skills library" directory. The generic name doesn't convey the purpose.

### The Solution: Tool Renaming

Rename tools to reflect their actual purpose:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/skills]
    tools:
      read_file:
        name: get_skill
        description: |
          Retrieve a skill document from the skills library.
          
          Skills are markdown files organized by category.
          Example: "python/debugging.md", "deployment/kubernetes.md"
      list_directory:
        name: list_skill_categories
        description: "List available skill categories"
      directory_tree:
        name: browse_skills
        description: "Show the complete skills library structure"
```

**Result**: The LLM sees `get_skill`, `list_skill_categories`, `browse_skills` — purpose-driven names that guide correct usage.

---

## Exposing Implementation Details

### The Problem

Your `directory_tree` tool requires a `path` parameter, but you always want it to start at the root. Exposing `path` lets the LLM pass arbitrary values, potentially accessing unintended directories.

### The Solution: Parameter Binding

Hide parameters and set fixed values:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/skills]
    tools:
      directory_tree:
        name: show_skills_structure
        parameters:
          path:
            hidden: true      # Remove from exposed schema
            default: "."      # Always use root directory
```

**Result**: The LLM calls `show_skills_structure()` with no arguments. The proxy injects `path="."` automatically.

### Variation: Rename Parameters

Sometimes you want to expose the parameter but with a better name:

```yaml
      read_file:
        name: get_skill
        parameters:
          path:
            rename: skill_path
            description: "Path to skill file (e.g., 'python/debugging.md')"
```

**Result**: The LLM sees `skill_path` instead of generic `path`.

### Variation: Optional with Default

Make a required parameter optional:

```yaml
      list_directory:
        name: list_skills
        parameters:
          path:
            rename: category
            default: "."
            description: "Category to list (default: all categories)"
```

**Result**: `list_skills()` works (uses root), but `list_skills(category="python")` also works.

---

## Need to Search Multiple Sources

### The Problem

You want to search code, documentation, and Slack simultaneously. Currently, the LLM has to call each search tool separately and wait for results sequentially.

### The Solution: Concurrent Composition

Create a composite tool that fans out to multiple upstreams concurrently:

```yaml
tool_views:
  unified:
    composite_tools:
      search_everything:
        description: |
          Search all knowledge sources simultaneously.
          Returns results from code, docs, and Slack concurrently.
        inputs:
          query:
            type: string
            required: true
            description: "Search query"
          max_results:
            type: integer
            required: false
            description: "Max results per source (default: 10)"
        parallel:
          code:
            tool: github.search_code
            args:
              query: "{inputs.query}"
              per_page: "{inputs.max_results|default:10}"
          docs:
            tool: confluence.search
            args:
              query: "{inputs.query}"
              limit: "{inputs.max_results|default:10}"
          slack:
            tool: slack.search_messages
            args:
              query: "{inputs.query}"
              limit: "{inputs.max_results|default:10}"
```

**Result**: One call to `search_everything(query="kubernetes deployment")` triggers three concurrent searches (via `asyncio.gather`). Results return as:

```json
{
  "code": [...github results...],
  "docs": [...confluence results...],
  "slack": [...slack results...]
}
```

---

## Different Users Need Different Tools

### The Problem

You want to give some users read-only access, others full access, and specialized teams only their relevant tools.

### The Solution: Multiple Views

Create different views for different access levels:

```yaml
tool_views:
  # Safe exploration - no write operations
  readonly:
    description: "Read-only tools for safe exploration"
    tools:
      filesystem:
        read_file: {}
        list_directory: {}
        directory_tree: {}
      github:
        search_code: {}
        search_issues: {}
        get_file_contents: {}

  # Full access for trusted operations
  admin:
    description: "Full access to all tools"
    include_all: true

  # Specialized view for deployment team
  deployment:
    description: "Kubernetes and deployment tools"
    tools:
      kubernetes:
        get_pods: {}
        get_deployments: {}
        scale_deployment: {}
        get_logs: {}
      github:
        create_pull_request: {}
        merge_pull_request: {}
```

**Result**: Access different views via HTTP endpoints:
- `/view/readonly/mcp` — Safe for exploration
- `/view/admin/mcp` — Full access
- `/view/deployment/mcp` — Deployment team only

Or configure different Claude Desktop instances to use different views.

### Variation: Runtime Permission Checks

Views control which tools are *available*, but sometimes you need to check permissions at runtime—for example, verifying OAuth scopes before allowing a write operation.

Use a pre-call hook to inspect the request and enforce permissions:

```python
# myhooks/permissions.py
import jwt
from mcp_proxy.hooks import HookResult, ToolCallContext
from fastmcp.server.dependencies import get_http_request

# Tools that require the "write" scope
WRITE_TOOLS = {"write_file", "delete_file", "create_deployment", "scale_deployment"}

async def check_permissions(args: dict, context: ToolCallContext) -> HookResult:
    """Verify OAuth scopes before allowing tool execution."""
    if context.tool_name not in WRITE_TOOLS:
        return HookResult()  # Read operations allowed

    # Get the HTTP request from FastMCP's context
    try:
        request = get_http_request()
    except RuntimeError:
        # No HTTP request (stdio mode) - allow or deny based on policy
        return HookResult()

    # Extract and decode the JWT
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return HookResult(abort=True, abort_reason="Missing authorization")

    token = auth_header[7:]
    try:
        # In production, verify signature with your OAuth provider's public key
        claims = jwt.decode(token, options={"verify_signature": False})
        scopes = claims.get("scope", "").split()
    except jwt.InvalidTokenError:
        return HookResult(abort=True, abort_reason="Invalid token")

    # Check for required scope
    if "write" not in scopes:
        return HookResult(
            abort=True,
            abort_reason=f"Scope 'write' required for {context.tool_name}"
        )

    return HookResult()
```

Configure the hook in your view:

```yaml
tool_views:
  production:
    hooks:
      pre_call: myhooks.permissions.check_permissions
    include_all: true
```

**Result**: All tools are exposed, but write operations require the `write` scope in the OAuth token. Users without the scope can still read, but writes are blocked at runtime with a clear error message.

**Note**: This example decodes the JWT without signature verification for brevity. In production, verify the signature using your OAuth provider's JWKS endpoint and the `pyjwt` library with `algorithms` and `audience` parameters.

---

## Want to Log or Audit Tool Calls

### The Problem

You need to log all tool calls for debugging, auditing, or analytics. You might also want to validate arguments before they reach upstream servers.

### The Solution: Hooks (YAML-Configurable)

For simple tool call logging, attach pre/post call hooks to views:

```yaml
tool_views:
  audited:
    description: "All tools with audit logging"
    hooks:
      pre_call: myapp.hooks.audit_call
      post_call: myapp.hooks.audit_result
    include_all: true
```

Implement the hooks:

```python
# myapp/hooks.py
import json
import logging
from datetime import datetime
from mcp_proxy.hooks import HookResult, ToolCallContext

logger = logging.getLogger("audit")

async def audit_call(args: dict, context: ToolCallContext) -> HookResult:
    """Log every tool call before execution."""
    logger.info(json.dumps({
        "event": "tool_call",
        "timestamp": datetime.utcnow().isoformat(),
        "tool": context.tool_name,
        "server": context.upstream_server,
        "args": args
    }))
    return HookResult(args=args)

async def audit_result(result, args: dict, context: ToolCallContext) -> HookResult:
    """Log every tool result after execution."""
    logger.info(json.dumps({
        "event": "tool_result",
        "timestamp": datetime.utcnow().isoformat(),
        "tool": context.tool_name,
        "success": not isinstance(result, Exception)
    }))
    return HookResult(result=result)
```

### Variation: Validation Hook

Block dangerous operations:

```python
async def validate_args(args: dict, context: ToolCallContext) -> HookResult:
    """Block writes to sensitive paths."""
    if context.tool_name == "write_file":
        path = args.get("path", "")
        if path.startswith("/etc/") or path.startswith("/root/"):
            return HookResult(
                abort=True,
                abort_reason="Cannot write to system directories"
            )
    return HookResult(args=args)
```

### Alternative: FastMCP Middleware (More Comprehensive)

Our hooks intercept only tool calls within views. For broader interception—including resource reads, prompt requests, tool listing, and all MCP messages—use [FastMCP Middleware](https://gofastmcp.com/servers/middleware).

FastMCP middleware operates as a pipeline, intercepting every MCP request and response:

```python
# mymiddleware.py
from fastmcp.server.middleware import Middleware, MiddlewareContext

class AuditMiddleware(Middleware):
    """Log all MCP operations, not just tool calls."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Log tool calls."""
        print(f"Tool call: {context.message.name}")
        result = await call_next(context)
        print(f"Tool completed: {context.message.name}")
        return result

    async def on_list_tools(self, context: MiddlewareContext, call_next):
        """Log when clients discover tools."""
        print("Client listing tools")
        return await call_next(context)

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        """Log resource access."""
        print(f"Resource read: {context.message.uri}")
        return await call_next(context)
```

FastMCP provides built-in middleware for common patterns:

```python
from fastmcp.server.middleware.timing import TimingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware

mcp.add_middleware(TimingMiddleware())     # Performance monitoring
mcp.add_middleware(LoggingMiddleware())    # Request logging
```

**When to use each:**

| Feature | Our Hooks | FastMCP Middleware |
|---------|-----------|-------------------|
| Tool call logging | ✅ YAML config | ✅ Python class |
| Resource/prompt logging | ❌ | ✅ |
| Tool listing interception | ❌ | ✅ |
| Rate limiting | ❌ | ✅ Built-in |
| Caching | ✅ Output caching | ✅ Request caching |
| Per-view configuration | ✅ | ❌ Server-wide |

Use our hooks for simple per-view tool logging. Use FastMCP middleware when you need to intercept all MCP protocol operations or want built-in patterns like rate limiting

---

## Need Custom Business Logic

### The Problem

You need a tool that combines multiple upstream calls with custom logic—something that can't be expressed as simple concurrent composition.

### The Solution: Custom Python Tools

Write a Python function with full access to upstream servers:

```python
# mytools.py
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(
    name="smart_file_search",
    description="Search for files, then read the most relevant one"
)
async def smart_file_search(
    query: str,
    ctx: ProxyContext
) -> dict:
    # Step 1: Search for matching files
    search_results = await ctx.call_tool(
        "filesystem.search_files",
        query=query
    )

    if not search_results:
        return {"found": False, "message": "No matching files"}

    # Step 2: Pick the best match (custom logic)
    best_match = search_results[0]  # Simplified; add ranking logic

    # Step 3: Read the file
    content = await ctx.call_tool(
        "filesystem.read_file",
        path=best_match["path"]
    )

    return {
        "found": True,
        "path": best_match["path"],
        "content": content,
        "other_matches": search_results[1:5]
    }
```

Register in config:

```yaml
tool_views:
  smart:
    custom_tools:
      - module: mytools.smart_file_search
    tools:
      filesystem:
        read_file: {}  # Also expose direct access
```

---

## Large Tool Outputs Waste Context

### The Problem

Some tools return huge outputs (file contents, search results). These consume valuable context window space, leaving less room for conversation and reasoning.

Consider an agent reading a 150KB log file. That's ~40,000 tokens stuffed into context, leaving almost no room for the LLM to actually think about the data.

### The Solution: Output Caching

Enable output caching to store large results and return only a preview with a signed retrieval URL:

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600        # URLs valid for 1 hour
  preview_chars: 500       # Show first 500 chars inline
  min_size: 10000          # Only cache outputs > 10KB

cache_secret: "${CACHE_SECRET}"  # HMAC signing key
cache_base_url: "https://your-proxy.example.com"

mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /data]
    cache_outputs:
      enabled: true
```

**Result**: Large outputs return as:

```json
{
  "cached": true,
  "preview": "First 500 characters of the file...",
  "token": "abc123",
  "retrieve_url": "https://your-proxy.example.com/cache/abc123?expires=...",
  "expires_at": "2025-01-13T20:00:00Z",
  "size_bytes": 248000
}
```

The LLM can:
1. Use the preview if sufficient
2. Call `retrieve_cached_output(token="abc123")` to load full content
3. Generate code that fetches the URL directly
4. **Delegate to a sub-agent** that processes the data in its own context

### Advanced: Recursive Language Model (RLM) Pattern

Output caching enables a powerful pattern for context-efficient agents: instead of passing data by value (stuffing it into context), you pass data **by reference** (the signed URL).

This is the **Recursive Language Model (RLM)** pattern. Here's how it works with a coding agent:

**Scenario**: User asks "Analyze this JSON log file and summarize error patterns."

**Without caching** (traditional approach):
```
Agent calls read_file("application.log")
  → 150KB JSON stuffed into context (~40,000 tokens)
  → Agent tries to reason about the data
  → Context exhausted, poor analysis
```

**With caching** (RLM pattern):
```
Agent calls read_file("application.log")
  → Receives: {token, preview, size_bytes: 153600, retrieve_url: "..."}
  → Agent sees the preview, understands the structure
  → Agent spawns a sub-agent with instructions:

    "You have access to a cached file via this URL:
     https://proxy.local:8000/cache/abc123?expires=...&sig=...

     Task: Extract all ERROR entries, group by message pattern,
     and return a summary with counts and timestamps.
     Use jq or Python to process the file."

  → Sub-agent (fresh context window):
    - Fetches the URL with curl
    - Processes with jq: select(.level == "ERROR") | group_by(.message)
    - Returns structured summary (~200 tokens)

  → Parent agent receives summary, has full context for reasoning
```

The parent agent never loaded the raw data. The sub-agent processed it in isolation using shell tools, returning only what was needed.

**Why the signed URL is essential**:

The URL is a **capability token**—possession grants access to exactly one file, for a limited time:

- **HMAC signature** prevents forging access to other files
- **Expiration timestamp** limits the access window
- **Random token** is unguessable

This makes it safe to pass the URL to sub-agents or LLM-generated code. The sub-agent can fetch the data, but can't access anything else.

**Example sub-agent workflow**:

```bash
# Sub-agent executes this to process the cached file
curl -s "https://proxy.local:8000/cache/abc123?expires=1706303600&sig=..." \
  | jq '[.[] | select(.level == "ERROR" or .level == "FATAL")]' \
  | jq 'group_by(.message | split(":")[0]) | map({
      pattern: .[0].message | split(":")[0],
      count: length,
      first: (sort_by(.timestamp) | first | .timestamp),
      last: (sort_by(.timestamp) | last | .timestamp)
    })'
```

**Result**:
```json
[
  {"pattern": "Connection timeout", "count": 847, "first": "2025-01-27T00:12:33Z", "last": "2025-01-27T18:45:02Z"},
  {"pattern": "Database deadlock", "count": 23, "first": "2025-01-27T03:22:11Z", "last": "2025-01-27T15:08:44Z"},
  {"pattern": "Out of memory", "count": 5, "first": "2025-01-27T08:00:00Z", "last": "2025-01-27T08:02:15Z"}
]
```

The parent agent receives ~200 tokens instead of ~40,000. It has plenty of context remaining to reason about the patterns, correlate with other information, and provide actionable insights.

**When to use this pattern**:

- Processing large files (logs, data exports, codebases)
- When the LLM needs to reason about results, not just return them
- With coding agents that can spawn sub-agents (Claude, Augment, Cursor, etc.)
- When you have shell tools available for data processing (jq, grep, awk)

---

## Summary

| Problem | Solution | Key Config |
|---------|----------|------------|
| Too many tools | Search mode | `exposure_mode: search` |
| Generic names | Tool renaming | `name: new_name` |
| Implementation details | Parameter binding | `hidden: true`, `default: value` |
| Sequential searches | Concurrent composition | `composite_tools.parallel` |
| Access control | Multiple views | `tool_views` with different tools |
| Audit/logging | Hooks | `hooks.pre_call`, `hooks.post_call` |
| Custom logic | Python tools | `custom_tools` |
| Large outputs | Output caching | `output_cache.enabled: true` |

For complete syntax and all options, see the **[Reference](reference.md)**.

