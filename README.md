# MCP Tool View Proxy

An MCP proxy server that aggregates tools from multiple upstream MCP servers and exposes them through **tool views** — filtered, transformed, and composed subsets of tools.

## Features

- **Tool aggregation**: Connect to multiple upstream MCP servers (stdio or HTTP)
- **Tool filtering**: Expose only specific tools from each server
- **Description overrides**: Customize tool descriptions with `{original}` placeholder
- **Tool views**: Named configurations exposing different tool subsets
- **Parallel composition**: Fan-out tools that call multiple upstream tools concurrently
- **Custom tools**: Python-defined tools with full access to upstream servers
- **Pre/post hooks**: Intercept and modify tool calls and results
- **Multi-transport**: Serve via stdio or HTTP with view-based routing
- **CLI management**: Add servers, create views, and manage configuration

## Installation

```bash
# Install from source
uv pip install -e .

# With dev dependencies
uv pip install -e ".[dev]"
```

## Quick Start

### 1. Create a configuration file

```yaml
# config.yaml
mcp_servers:
  memory:
    command: uv
    args: [tool, run, --from, agent-memory-server, agent-memory, mcp]
    env:
      REDIS_URL: redis://localhost:6379

tool_views:
  assistant:
    description: "Memory tools for AI assistant"
    tools:
      memory:
        search_long_term_memory: {}
        create_long_term_memories: {}
```

### 2. Start the proxy

```bash
# Stdio transport (for MCP clients)
mcp-proxy serve --config config.yaml

# HTTP transport (for web clients)
mcp-proxy serve --config config.yaml --transport http --port 8000
```

### 3. Use with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "proxy": {
      "command": "mcp-proxy",
      "args": ["serve", "--config", "/path/to/config.yaml"]
    }
  }
}
```

## Configuration

### Upstream Servers

Define MCP servers to connect to:

```yaml
mcp_servers:
  # Stdio-based server (local command)
  local-server:
    command: python
    args: [-m, my_mcp_server]
    env:
      API_KEY: ${MY_API_KEY}  # Environment variable expansion

  # HTTP-based server (remote)
  remote-server:
    url: "https://api.example.com/mcp/"
    headers:
      Authorization: "Bearer ${ACCESS_TOKEN}"
```

### Tool Filtering

Filter tools at the server level:

```yaml
mcp_servers:
  github:
    url: "https://api.githubcopilot.com/mcp/"
    tools:
      search_code: {}
      search_issues: {}
      # Other tools from this server are not exposed
```

### Description Overrides

Customize tool descriptions:

```yaml
mcp_servers:
  memory:
    command: agent-memory
    tools:
      search_long_term_memory:
        description: |
          Search saved memories about past incidents.

          {original}
```

The `{original}` placeholder is replaced with the upstream tool's description.

### Tool Views

Create named views exposing different tool subsets:

```yaml
tool_views:
  # Direct mode: tools exposed with their names
  search-tools:
    description: "Read-only search tools"
    exposure_mode: direct
    tools:
      github:
        search_code: {}
        search_issues: {}

  # Search mode: exposes search_tools + call_tool meta-tools
  all-github:
    description: "All GitHub tools via search"
    exposure_mode: search
    include_all: true
```

### Parallel Composition

Create tools that call multiple upstream tools concurrently:

```yaml
tool_views:
  unified:
    composite_tools:
      search_everywhere:
        description: "Search all sources in parallel"
        inputs:
          query: { type: string, required: true }
        parallel:
          code:
            tool: github.search_code
            args: { query: "{inputs.query}" }
          memory:
            tool: memory.search_long_term_memory
            args: { text: "{inputs.query}" }
```

### Hooks

Attach pre/post call hooks to views:

```yaml
tool_views:
  monitored:
    hooks:
      pre_call: myapp.hooks.validate_args
      post_call: myapp.hooks.log_result
    tools:
      server:
        some_tool: {}
```

Hook implementation:

```python
# myapp/hooks.py
from mcp_proxy.hooks import HookResult, ToolCallContext

async def validate_args(args: dict, context: ToolCallContext) -> HookResult:
    # Modify args or abort
    return HookResult(args=args)

async def log_result(result, args: dict, context: ToolCallContext) -> HookResult:
    print(f"Tool {context.tool_name} returned: {result}")
    return HookResult(result=result)
```

### Custom Tools

Define Python tools with upstream access:

```python
# myapp/tools.py
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(
    name="smart_search",
    description="Search with context enrichment"
)
async def smart_search(query: str, ctx: ProxyContext) -> dict:
    # Call upstream tools
    memory = await ctx.call_tool("memory.search_long_term_memory", text=query)
    code = await ctx.call_tool("github.search_code", query=query)
    return {"memory": memory, "code": code}
```

Register in config:

```yaml
tool_views:
  smart:
    custom_tools:
      - module: myapp.tools.smart_search
```


## CLI Reference

### Server Management

```bash
# List configured servers
mcp-proxy servers

# Add a stdio server
mcp-proxy server add myserver --command python --args "-m,mymodule"

# Add an HTTP server
mcp-proxy server add remote --url "https://api.example.com/mcp/"

# Set tool allowlist for a server
mcp-proxy server set-tools myserver "tool1,tool2,tool3"

# Set custom tool description
mcp-proxy server set-tool-description myserver mytool "Custom description. {original}"

# Remove a server
mcp-proxy server remove myserver
```

### View Management

```bash
# List views
mcp-proxy view list

# Create a view
mcp-proxy view create myview --description "My tools" --exposure-mode direct

# Add server to view
mcp-proxy view add-server myview myserver --tools "tool1,tool2"

# Set tools for a server in a view
mcp-proxy view set-tools myview myserver "tool1,tool2,tool3"

# Delete a view
mcp-proxy view delete myview
```

### Inspection and Debugging

```bash
# Show tool schemas from upstream servers
mcp-proxy schema
mcp-proxy schema myserver.mytool
mcp-proxy schema --server myserver --json

# Validate configuration
mcp-proxy validate
mcp-proxy validate --check-connections

# Call a tool directly
mcp-proxy call myserver.mytool --arg key=value

# Show resolved configuration
mcp-proxy config --resolved
```

## HTTP Endpoints

When running with `--transport http`, the proxy exposes:

| Endpoint | Description |
|----------|-------------|
| `/mcp` | Default MCP endpoint (all server tools) |
| `/view/{name}/mcp` | View-specific MCP endpoint |
| `/views` | List all available views |
| `/views/{name}` | Get view details |
| `/health` | Health check |

Example requests:

```bash
# List views
curl http://localhost:8000/views

# Get view info
curl http://localhost:8000/views/assistant

# Health check
curl http://localhost:8000/health
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Proxy Server                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                      Tool Views                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │  │
│  │  │  assistant  │  │   search    │  │   all-tools     │    │  │
│  │  │  - memory   │  │ - search_*  │  │ - include_all   │    │  │
│  │  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘    │  │
│  └─────────┼────────────────┼──────────────────┼─────────────┘  │
│            │                │                  │                 │
│  ┌─────────▼────────────────▼──────────────────▼─────────────┐  │
│  │                    Hook System                             │  │
│  │  pre_call(args, ctx) → modified_args                       │  │
│  │  post_call(result, args, ctx) → modified_result            │  │
│  └─────────┬────────────────┬──────────────────┬─────────────┘  │
│            │                │                  │                 │
│  ┌─────────▼────────────────▼──────────────────▼─────────────┐  │
│  │                 Upstream MCP Clients                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │  │
│  │  │   memory     │  │   github     │  │  filesystem  │     │  │
│  │  │   (stdio)    │  │   (http)     │  │   (stdio)    │     │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .

# Format code
ruff format .
```

## License

MIT
