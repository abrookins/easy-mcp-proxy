# Tutorial: Getting Started with Easy MCP Proxy

This tutorial walks you through Easy MCP Proxy from installation to advanced features. By the end, you'll understand how to aggregate, filter, transform, and compose MCP tools.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- An MCP client with local stdio, OAuth HTTP, or bearer API key support
- Node.js and `npx` for the filesystem examples
- The owner's verified OAuth issuer and subject; HTTP also needs the provider
  settings in the [authentication reference](reference.md#authentication)

## Step 1: Installation

```bash
# Clone the repository
git clone https://github.com/abrookins/easy-mcp-proxy.git
cd easy-mcp-proxy

# Install
uv sync --frozen
```

Verify the installation:

```bash
uv run mcp-proxy --help
```

## Step 2: Your First Configuration

Create a file called `config.yaml`. This is an import/inspection input, not the
running service's configuration. If upgrading an existing service, follow the
[migration guide](user-owned-configuration.md#migrate-an-existing-installation)
first to preserve its OAuth state.

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
uv run mcp-proxy validate --config config.yaml
```

See what tools will be exposed:

```bash
uv run mcp-proxy schema --config config.yaml
```

Call a tool directly to test:

```bash
uv run mcp-proxy call filesystem.read_file --config config.yaml --arg path=/tmp/mcp-demo/hello.txt
```

Use an absolute path inside the directory allowed by the filesystem server.

## Step 4: Provision, Import, and Run

Use a new private state directory for this tutorial. Substitute the owner's
verified issuer and subject; an email address is not the ownership key.

```bash
export MCP_PROXY_STATE_DIR="$HOME/.local/state/easy-mcp-proxy-demo"
export MCP_PROXY_OWNER_ISSUER='https://YOUR-ISSUER/'
export MCP_PROXY_OWNER_SUBJECT='VERIFIED-SUBJECT'
proxy_user_id=$(uv run mcp-proxy users provision \
  --issuer "$MCP_PROXY_OWNER_ISSUER" --subject "$MCP_PROXY_OWNER_SUBJECT" --operator)
uv run mcp-proxy users grant "$proxy_user_id" \
  --client mcp-proxy-local --admin --view '*'
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml --apply
```

The first import is a dry run. Operator status permits the process and destination
changes in this tutorial. Use narrower grants for normal runtime applications.

### Option A: Stdio (for a local client)

With those environment variables set:

```bash
uv run mcp-proxy serve
```

Alternatively, have your desktop client launch the process. For a client that
uses an `mcpServers` configuration, supply absolute paths and the same identity:

```json
{
  "mcpServers": {
    "proxy": {
      "command": "/ABSOLUTE/PATH/TO/uv",
      "args": ["run", "--project", "/ABSOLUTE/PATH/TO/easy-mcp-proxy", "mcp-proxy", "serve"],
      "env": {
        "MCP_PROXY_STATE_DIR": "/ABSOLUTE/PATH/TO/easy-mcp-proxy-demo",
        "MCP_PROXY_OWNER_ISSUER": "https://YOUR-ISSUER/",
        "MCP_PROXY_OWNER_SUBJECT": "VERIFIED-SUBJECT"
      }
    }
  }
}
```

Run either the terminal process or the client-launched process. A second process
cannot open the same state directory while the first is serving. Stdio exposes
the owner's default view and uses the explicit `mcp-proxy-local` grant.

### Option B: HTTP (for remote clients)

Stop the stdio process before using its state directory for HTTP. Configure
[OAuth](reference.md#authentication), grant browser administration, and start:

```bash
uv run mcp-proxy users grant "$proxy_user_id" \
  --client mcp-proxy-browser --admin --view '*'
uv run mcp-proxy serve --transport http --port 8000
```

`MCP_PROXY_HOST` defaults to `127.0.0.1`. Put the remote service behind HTTPS at
its configured public origin. `/health` is public; `/views` and MCP endpoints
require OAuth or a user-bound API key and explicit client grants. For OAuth,
register each remote client and grant
its downstream client ID the views it needs, as described in the
[bootstrap guide](user-owned-configuration.md#bootstrap-and-grants).

Open `/config` to edit configuration. Connect the MCP client to `/mcp` for its
owner's default view or `/view/NAME/mcp` for a granted named view.

### Apply the remaining examples

The following YAML examples describe fields to add or change. For an HTTP
service, edit their JSON equivalent in `/config`, preview, optionally probe an
upstream, then apply. New views also require a matching client grant. For local
stdio, stop the process, update the YAML, repeat the dry-run/import commands,
and restart it. File inspection commands continue to read YAML; they do not
inspect or modify the running managed service.

HTTP updates reuse unchanged connections and drain replaced connections for up
to 10 seconds. Refresh the client's tool list if its discovery cache is stale.
See [live-change behavior](user-owned-configuration.md#live-change-behavior) for
limits and settings that still require a restart.

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

This exposes three tools:
- `everything_search_tools(query)` — Find tools by description
- `everything_describe_tool(tool_name)` — Inspect one exact exposed schema
- `everything_call_tool(tool_name, arguments)` — Validate and call a tool
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

This creates `{server}_search_tools`, `{server}_describe_tool`, and
`{server}_call_tool` for each upstream server.

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

These environment references are expanded by local inspection/import. A running
service reads the imported values. Remote edits must use actual values or
existing secret references; `${...}` is rejected.

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

## Step 15: Safe Output Handling

Large tool outputs (file contents, search results, minified JSON, JSONL, logs)
consume valuable context window space. Easy MCP Proxy protects proxied tool calls
by default: after an upstream server responds, the proxy measures the result,
caches oversized or overlong-line output, and returns only a bounded preview.

Use `output_cache` when you want to tune those defaults:

```yaml
output_cache:
  enabled: true             # Set false only for explicit opt-out
  ttl_seconds: 3600         # URLs valid for 1 hour
  max_inline_tokens: 3000   # Default model-visible budget
  max_line_chars: 1200      # Prevent giant single lines
  retrieval_default_line_count: 100
  retrieval_max_chars: 12000

mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /data]
```

The service manages cache keys and retrieval URLs per owner/view. HTTP retrieval
requires the signed URL plus OAuth, a bound API key, or an authorized browser session for the same
owner/view. Do not set `cache_secret` or `cache_base_url` in managed config.

When a tool returns output larger than the inline limits, the proxy returns:

```json
{
  "cached": true,
  "cache_id": "abc123",
  "token": "abc123",
  "truncated": true,
  "truncation_reasons": ["estimated_tokens", "max_line_chars"],
  "preview": "Bounded preview...",
  "retrieve_url": "https://your-proxy.example.com/view/default/cache/abc123?expires=...&sig=...",
  "expires_at": "2026-07-31T20:00:00Z",
  "size_bytes": 248000,
  "original": {"bytes": 248000, "estimated_tokens": 62000},
  "returned": {"bytes": 1200, "estimated_tokens": 300},
  "navigation": {
    "preview_tool": "preview_cached_output",
    "range_tool": "range_cached_output",
    "query_tool": "query_cached_output"
  }
}
```

The LLM can:
1. Use the preview if it contains enough information
2. Call `preview_cached_output(token="abc123", line_count=200)` for a line window
3. Call `range_cached_output(token="abc123", char_offset=1200, char_count=4000)`
   for minified or single-line content
4. Call `query_cached_output(token="abc123", jmespath_expression="items[].title")`
   for JSON slices
5. Generate code that fetches the URL with `download=1` for full-content
   processing outside the model context

You can configure limits per-server or per-tool:

```yaml
mcp_servers:
  filesystem:
    cache_outputs:
      enabled: true
      max_line_chars: 800
    tools:
      read_file:
        cache_output:
          enabled: true
          max_inline_tokens: 4000
```

## Next Steps

You now understand the core features. For more:

- **[Use Cases](use-cases.md)** — See how features solve specific problems
- **[Reference](reference.md)** — Complete syntax and options for every feature
- **[CLI Reference](reference.md#cli-reference)** — All available commands
