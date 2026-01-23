# Tutorial: Getting Started with Easy MCP Proxy

This tutorial walks you through Easy MCP Proxy from installation to advanced features. By the end, you'll understand how to aggregate, filter, transform, and compose MCP tools.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- An MCP client (Claude Desktop, or any MCP-compatible client)

## Step 1: Installation

```bash
# Clone the repository
git clone https://github.com/abrookins/easy-mcp-proxy.git
cd easy-mcp-proxy

# Install
uv pip install -e .
```

Verify the installation:

```bash
mcp-proxy --help
```

## Step 2: Your First Configuration

Create a file called `config.yaml`:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]

tool_views:
  default:
    description: "File operations"
    tools:
      filesystem:
        read_file: {}
        write_file: {}
        list_directory: {}
```

This configuration:
1. Defines an upstream server called `filesystem` using the official MCP filesystem server
2. Creates a view called `default` exposing three specific tools

Create the demo directory:

```bash
mkdir -p /tmp/mcp-demo
echo "Hello from MCP!" > /tmp/mcp-demo/hello.txt
```

## Step 3: Test the Configuration

Validate your config:

```bash
mcp-proxy validate --config config.yaml
```

See what tools will be exposed:

```bash
mcp-proxy schema --config config.yaml
```

Call a tool directly to test:

```bash
mcp-proxy call filesystem.read_file --config config.yaml --arg path=hello.txt
```

Note: Paths are relative to the directory passed to the filesystem server (`/tmp/mcp-demo`).

## Step 4: Run the Proxy

### Option A: Stdio (for Claude Desktop)

```bash
mcp-proxy serve --config config.yaml
```

Add to Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "proxy": {
      "command": "uv",
      "args": ["run", "mcp-proxy", "serve", "--config", "/path/to/config.yaml"]
    }
  }
}
```

### Option B: HTTP (for web clients)

```bash
mcp-proxy serve --config config.yaml --transport http --port 8000
```

Test the endpoints:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/views
```

## Step 5: Add Tool Filtering

Let's say the filesystem server exposes 10 tools, but you only want 3. Update your config:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]
    tools:
      read_file: {}
      list_directory: {}
      # write_file, delete_file, etc. are NOT exposed
```

The `tools` section acts as an allowlist. Only listed tools pass through.

## Step 6: Build a Domain-Specific Interface

Let's build something useful: a "skills library" where you store reusable prompts, templates, and knowledge documents. Instead of exposing generic filesystem tools, we'll create a purpose-built interface.

First, create a skills directory:

```bash
mkdir -p /tmp/skills/python /tmp/skills/deployment
echo "# Python Debugging\n\nUse pdb: import pdb; pdb.set_trace()" > /tmp/skills/python/debugging.md
echo "# Kubernetes Basics\n\nkubectl get pods -A" > /tmp/skills/deployment/kubernetes.md
```

Now configure the proxy to expose this as a skills library:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/skills]
    tools:
      read_file:
        name: get_skill
        description: |
          Retrieve a skill document from the skills library.

          Skills are markdown files organized by category.
          Examples: "python/debugging.md", "deployment/kubernetes.md"
      list_directory:
        name: list_skills
        description: "List skills in a category (e.g., 'python') or all categories"
      directory_tree:
        name: browse_skills
        description: "Show the complete skills library structure"
```

The LLM now sees `get_skill`, `list_skills`, `browse_skills` — purpose-driven names that guide correct usage.

## Step 7: Parameter Binding

Let's improve the skills interface further. The `browse_skills` tool has a `path` parameter, but we always want it to show the entire library. Hide the parameter and set a default:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/skills]
    tools:
      directory_tree:
        name: browse_skills
        description: "Show the complete skills library structure"
        parameters:
          path:
            hidden: true    # Remove from exposed schema
            default: "."    # Always start at root
      read_file:
        name: get_skill
        parameters:
          path:
            rename: skill_path
            description: "Path to skill (e.g., 'python/debugging.md')"
      list_directory:
        name: list_skills
        parameters:
          path:
            rename: category
            default: "."
            description: "Category to list, or omit for all categories"
```

Now:
- `browse_skills()` takes no arguments — the proxy injects `path="."`
- `get_skill(skill_path="python/debugging.md")` uses a domain-specific parameter name
- `list_skills()` works (shows all), and `list_skills(category="python")` filters

## Step 8: Multiple Servers

Add more upstream servers:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]

  github:
    command: npx
    args: [-y, "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}

tool_views:
  default:
    tools:
      filesystem:
        read_file: {}
      github:
        search_repositories: {}
        get_file_contents: {}
```

Now both servers' tools are available through one proxy.

## Step 9: Search Mode for Many Tools

When you have dozens of tools, listing them all overwhelms the LLM. Use search mode:

```yaml
tool_views:
  everything:
    description: "All tools via search"
    exposure_mode: search
    include_all: true
```

This exposes just two tools:
- `everything_search_tools(query)` — Find tools by description
- `everything_call_tool(tool_name, arguments)` — Call a tool by name

The LLM searches first, then calls. Much cleaner than 50 individual tools.

### Search Per Server

For better organization, use `search_per_server`:

```yaml
tool_views:
  organized:
    exposure_mode: search_per_server
    include_all: true
```

This creates `{server}_search_tools` and `{server}_call_tool` for each upstream server.

## Step 10: Composite Tools (Concurrent Execution)

Create tools that call multiple upstream tools concurrently:

```yaml
tool_views:
  unified:
    composite_tools:
      search_everywhere:
        description: "Search files and GitHub concurrently"
        inputs:
          query: { type: string, required: true }
        parallel:
          files:
            tool: filesystem.search_files
            args: { query: "{inputs.query}" }
          code:
            tool: github.search_code
            args: { query: "{inputs.query}" }
```

When the LLM calls `search_everywhere(query="deployment")`, both searches run concurrently and results are combined.

## Step 11: Custom Python Tools

For complex logic, write Python tools:

```python
# mytools.py
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(
    name="smart_search",
    description="Search with automatic context enrichment"
)
async def smart_search(query: str, ctx: ProxyContext) -> dict:
    # Call multiple upstream tools
    search_results = await ctx.call_tool(
        "github.search_code",
        query=query
    )

    # Process results
    if not search_results:
        return {"message": "No results found", "query": query}

    return {
        "query": query,
        "results": search_results,
        "count": len(search_results)
    }
```

Register in config:

```yaml
tool_views:
  smart:
    custom_tools:
      - module: mytools.smart_search
```

## Step 12: Hooks for Logging and Validation

Add pre/post call hooks:

```yaml
tool_views:
  monitored:
    hooks:
      pre_call: myapp.hooks.log_call
      post_call: myapp.hooks.log_result
    tools:
      filesystem:
        read_file: {}
```

Implement the hooks:

```python
# myapp/hooks.py
from mcp_proxy.hooks import HookResult, ToolCallContext

async def log_call(args: dict, context: ToolCallContext) -> HookResult:
    print(f"Calling {context.tool_name} with {args}")
    return HookResult(args=args)  # Pass through unchanged

async def log_result(result, args: dict, context: ToolCallContext) -> HookResult:
    print(f"{context.tool_name} returned: {result}")
    return HookResult(result=result)  # Pass through unchanged
```

Hooks can also modify arguments, transform results, or abort calls.

## Step 13: HTTP Servers (Remote MCP)

Connect to remote MCP servers over HTTP:

```yaml
mcp_servers:
  zapier:
    url: "https://actions.zapier.com/mcp/YOUR_ID/sse"
    headers:
      Authorization: "Bearer ${ZAPIER_API_KEY}"
```

Environment variables are expanded at runtime.

## Step 14: Multiple Views

Create different views for different use cases:

```yaml
tool_views:
  # Read-only view for safe exploration
  readonly:
    description: "Safe read-only tools"
    tools:
      filesystem:
        read_file: {}
        list_directory: {}
      github:
        search_code: {}

  # Full access for trusted operations
  full:
    description: "All operations"
    include_all: true

  # Specialized view for a specific task
  deployment:
    description: "Deployment tools only"
    tools:
      kubernetes:
        get_pods: {}
        get_deployments: {}
        scale_deployment: {}
```

Access views via HTTP endpoints:
- `/view/readonly/mcp`
- `/view/full/mcp`
- `/view/deployment/mcp`

## Step 15: Output Caching

Large tool outputs (file contents, search results) consume valuable context window space. Enable output caching to store large results and return only a preview:

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600        # URLs valid for 1 hour
  preview_chars: 500       # Show first 500 chars inline
  min_size: 10000          # Only cache outputs > 10KB

cache_secret: "${CACHE_SECRET}"  # HMAC signing key (set via environment variable)
cache_base_url: "https://your-proxy.example.com"  # Base URL for retrieval (HTTP mode)

mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /data]
```

When a tool returns output larger than `min_size`, the proxy returns:

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
1. Use the preview if it contains enough information
2. Call `retrieve_cached_output(token="abc123")` to load the full content
3. Generate code that fetches the URL directly

You can also configure caching per-server or per-tool:

```yaml
mcp_servers:
  filesystem:
    cache_outputs:
      enabled: true
      min_size: 5000  # Lower threshold for this server
    tools:
      read_file:
        cache_output:
          enabled: true
          preview_chars: 1000  # More preview for this tool
```

## Next Steps

You now understand the core features. For more:

- **[Use Cases](use-cases.md)** — See how features solve specific problems
- **[Reference](reference.md)** — Complete syntax and options for every feature
- **[CLI Reference](reference.md#cli-reference)** — All available commands

