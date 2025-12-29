# Easy MCP Proxy

An MCP proxy server that aggregates tools from multiple upstream MCP servers and exposes them through **tool views** — filtered, transformed, and composed subsets of tools.

## Features

- **Tool aggregation**: Connect to multiple upstream MCP servers (stdio or HTTP)
- **Tool filtering**: Expose only specific tools from each server
- **Tool renaming**: Expose tools under different names
- **Parameter binding**: Hide, rename, or set defaults for tool parameters
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
    
      command: uv
      "args": ["run", "--directory", "/path/to/repository/checkout", "serve", "--config", "/path/to/config.yaml"]
    }
  }
}
```

**NOTE**: If you don't pass `-c`, you will use the default config file
at ~/.config/mcp-proxy/config.yaml.

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

  # Stdio server with working directory
  # (useful for servers that resolve relative paths against CWD)
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /data/files]
    cwd: /data/files  # Relative paths in tool calls resolve against this

  # HTTP-based server (remote)
  zapier:
    url: "https://actions.zapier.com/mcp/YOUR_MCP_ID/sse"
    headers:
      Authorization: "Bearer ${ZAPIER_MCP_API_KEY}"
```

### Tool Filtering

Filter tools at the server level:

```yaml
mcp_servers:
  github:
    command: npx
    args: [-y, "@github/mcp-server"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}
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

### Tool Renaming

Expose tools under different names:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /data]
    tools:
      read_file:
        name: read_document  # Expose as 'read_document' instead of 'read_file'
      list_directory:
        name: list_folders
        description: "List folders in the data directory"
```

### Parameter Binding

Hide, rename, or set defaults for tool parameters. This is useful when wrapping
generic tools (like filesystem operations) to create domain-specific interfaces:

```yaml
mcp_servers:
  skills-server:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/skills]
    tools:
      directory_tree:
        name: get_skills_structure
        description: "Get the structure of the skills library"
        parameters:
          path:
            hidden: true      # Remove from exposed schema
            default: "."      # Always use root directory

      list_directory:
        name: list_skill_categories
        parameters:
          path:
            rename: category  # Expose as 'category' instead of 'path'
            default: "."      # Optional with default
            description: "Category folder to list (e.g., 'deployment')"

      read_file:
        name: read_skill
        parameters:
          path:
            rename: skill_path
            description: "Path to skill file (e.g., 'deployment/kubernetes.md')"
```

Parameter binding options:
- `hidden: true` - Remove parameter from exposed schema
- `default: value` - Default value (makes parameter optional, injected at call time)
- `rename: new_name` - Expose under a different name
- `description: text` - Override parameter description

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
mcp-proxy server list
mcp-proxy server list --verbose  # Show details
mcp-proxy server list --json     # JSON output

# Add a stdio server
mcp-proxy server add myserver --command python --args "-m,mymodule"

# Add an HTTP server
mcp-proxy server add remote --url "https://api.example.com/mcp/"

# Add with environment variables
mcp-proxy server add myserver --command myapp --env "API_KEY=xxx" --env "DEBUG=1"

# Remove a server
mcp-proxy server remove myserver
mcp-proxy server remove myserver --force  # Remove even if referenced by views
```

### Tool Configuration

```bash
# Set tool allowlist for a server (comma-separated)
mcp-proxy server set-tools myserver "tool1,tool2,tool3"

# Clear tool filter (expose all tools)
mcp-proxy server clear-tools myserver

# Rename a tool
mcp-proxy server rename-tool myserver original_name new_name

# Set custom tool description
mcp-proxy server set-tool-description myserver mytool "Custom description. {original}"

# Configure parameter binding
mcp-proxy server set-tool-param myserver mytool path --hidden --default "."
mcp-proxy server set-tool-param myserver mytool path --rename folder
mcp-proxy server set-tool-param myserver mytool query --description "Search query"
mcp-proxy server set-tool-param myserver mytool path --clear  # Remove config
```

### View Management

```bash
# List views
mcp-proxy view list
mcp-proxy view list --verbose
mcp-proxy view list --json

# Create a view
mcp-proxy view create myview --description "My tools"
mcp-proxy view create searchview --exposure-mode search

# Delete a view
mcp-proxy view delete myview

# Add/remove servers from views
mcp-proxy view add-server myview myserver --tools "tool1,tool2"
mcp-proxy view add-server myview myserver --all  # Include all tools
mcp-proxy view remove-server myview myserver

# Configure tools within a view
mcp-proxy view set-tools myview myserver "tool1,tool2,tool3"
mcp-proxy view clear-tools myview myserver
mcp-proxy view rename-tool myview myserver original_name new_name
mcp-proxy view set-tool-description myview myserver mytool "Description"
mcp-proxy view set-tool-param myview myserver mytool path --hidden --default "."
```

### Inspection and Debugging

```bash
# Show tool schemas from upstream servers
mcp-proxy schema
mcp-proxy schema myserver.mytool
mcp-proxy schema --server myserver
mcp-proxy schema --server myserver --json

# Validate configuration
mcp-proxy validate
mcp-proxy validate --check-connections  # Test upstream connectivity

# Call a tool directly (for testing)
mcp-proxy call myserver.mytool --arg key=value --arg count=10

# Show configuration
mcp-proxy config
mcp-proxy config --resolved  # With environment variables expanded

# Generate example files
mcp-proxy init config  # Example config.yaml
mcp-proxy init hooks   # Example hooks.py
```

### Running the Proxy

```bash
# Stdio transport (for MCP clients like Claude Desktop)
mcp-proxy serve
mcp-proxy serve --config /path/to/config.yaml

# HTTP transport (for web clients)
mcp-proxy serve --transport http --port 8000

# Load environment from .env file
mcp-proxy serve --env-file .env
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
│  │  │   memory     │  │   github     │  │    zapier    │     │  │
│  │  │   (stdio)    │  │   (stdio)    │  │   (http)     │     │  │
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

Copyright (C) 2025 Andrew Brookins

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

See [LICENSE](LICENSE) for the full license text.
