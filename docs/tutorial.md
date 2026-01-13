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
mcp-proxy call filesystem.read_file --config config.yaml --arg path=/tmp/mcp-demo/hello.txt
```

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

## Step 6: Rename Tools

Generic tool names like `read_file` can be confusing when you have multiple servers. Rename them:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]
    tools:
      read_file:
        name: read_document
        description: "Read a document from the demo folder"
      list_directory:
        name: list_documents
```

Now the LLM sees `read_document` instead of `read_file`.

## Step 7: Parameter Binding

Hide implementation details by binding parameters:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]
    tools:
      directory_tree:
        name: show_structure
        description: "Show the folder structure"
        parameters:
          path:
            hidden: true    # Don't expose this parameter
            default: "."    # Always use the root
```

The LLM calls `show_structure()` with no arguments. The proxy injects `path="."` automatically.

You can also rename parameters:

```yaml
      read_file:
        name: get_document
        parameters:
          path:
            rename: document_name
            description: "Name of the document to read"
```

## Step 8: Multiple Servers

Add more upstream servers:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /tmp/mcp-demo]

  memory:
    command: uv
    args: [tool, run, agent-memory, mcp]
    env:
      REDIS_URL: redis://localhost:6379

tool_views:
  default:
    tools:
      filesystem:
        read_file: {}
      memory:
        search_long_term_memory: {}
        create_long_term_memories: {}
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

## Step 10: Composite Tools (Parallel Execution)

Create tools that call multiple upstream tools simultaneously:

```yaml
tool_views:
  unified:
    composite_tools:
      search_everywhere:
        description: "Search files and memory in parallel"
        inputs:
          query: { type: string, required: true }
        parallel:
          files:
            tool: filesystem.search_files
            args: { query: "{inputs.query}" }
          memory:
            tool: memory.search_long_term_memory
            args: { text: "{inputs.query}" }
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
    memory_results = await ctx.call_tool(
        "memory.search_long_term_memory",
        text=query
    )

    # Process results
    if not memory_results:
        return {"message": "No results found", "query": query}

    return {
        "query": query,
        "results": memory_results,
        "count": len(memory_results)
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

## Next Steps

You now understand the core features. For more:

- **[Use Cases](use-cases.md)** — See how features solve specific problems
- **[Reference](reference.md)** — Complete syntax and options for every feature
- **[CLI Reference](reference.md#cli-reference)** — All available commands

