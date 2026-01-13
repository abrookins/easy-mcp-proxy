# Reference

Complete documentation for all Easy MCP Proxy features, configuration options, and CLI commands.

## Table of Contents

- [Configuration File](#configuration-file)
- [Upstream Servers](#upstream-servers)
- [Tool Configuration](#tool-configuration)
- [Parameter Binding](#parameter-binding)
- [Tool Views](#tool-views)
- [Exposure Modes](#exposure-modes)
- [Composite Tools](#composite-tools)
- [Custom Tools](#custom-tools)
- [Hooks](#hooks)
- [Output Caching](#output-caching)
- [Authentication](#authentication)
- [HTTP Endpoints](#http-endpoints)
- [CLI Reference](#cli-reference)

---

## Configuration File

Default location: `~/.config/mcp-proxy/config.yaml`

Override with `--config` flag:

```bash
mcp-proxy serve --config /path/to/config.yaml
```

### Top-Level Structure

```yaml
# Upstream MCP servers
mcp_servers:
  server_name:
    # Server configuration...

# Named tool views
tool_views:
  view_name:
    # View configuration...

# Output caching (optional)
output_cache:
  enabled: false
  ttl_seconds: 3600
  preview_chars: 500
  min_size: 10000

# Cache settings (required if output_cache enabled)
cache_secret: "${CACHE_SECRET}"
cache_base_url: "https://your-domain.com"
```

---

## Upstream Servers

### Stdio Server (Local Process)

```yaml
mcp_servers:
  myserver:
    command: python           # Required: executable
    args: [-m, mymodule]      # Optional: command arguments
    env:                      # Optional: environment variables
      API_KEY: ${MY_API_KEY}
    cwd: /path/to/dir         # Optional: working directory
    tools:                    # Optional: tool configuration
      tool_name: {}
```

### HTTP Server (Remote)

```yaml
mcp_servers:
  remote:
    url: "https://api.example.com/mcp/sse"  # Required: SSE endpoint
    headers:                                 # Optional: HTTP headers
      Authorization: "Bearer ${TOKEN}"
    tools:
      tool_name: {}
```

### Environment Variable Expansion

Use `${VAR_NAME}` syntax. Variables are expanded at runtime:

```yaml
env:
  API_KEY: ${MY_API_KEY}        # From environment
  DEBUG: "true"                  # Literal value
```

Load from `.env` file:

```bash
mcp-proxy serve --env-file .env
```

---

## Tool Configuration

Configure tools at the server level:

```yaml
mcp_servers:
  myserver:
    command: myapp
    tools:
      # Minimal: just include the tool
      tool_one: {}
      
      # With options
      tool_two:
        name: renamed_tool              # Expose under different name
        description: "Custom desc"      # Override description
        parameters:                     # Parameter configuration
          param_name:
            # Parameter options...
```

### Tool Options

| Option | Type | Description |
|--------|------|-------------|
| `name` | string | Expose tool under this name instead of original |
| `description` | string | Override tool description. Use `{original}` to include upstream description |
| `parameters` | object | Parameter binding configuration |
| `cache_output` | object | Per-tool output caching settings |

### Description Placeholder

```yaml
tools:
  search:
    description: |
      Search the knowledge base.
      
      {original}
      
      Note: Results are cached for 1 hour.
```

The `{original}` placeholder is replaced with the upstream tool's description.

---

## Parameter Binding

Transform tool parameters:

```yaml
tools:
  mytool:
    parameters:
      path:
        hidden: true           # Remove from schema
        default: "/data"       # Inject this value
      query:
        rename: search_term    # Expose as different name
        description: "What to search for"
      limit:
        default: 10            # Make optional with default
```

### Parameter Options

| Option | Type | Description |
|--------|------|-------------|
| `hidden` | boolean | Remove parameter from exposed schema |
| `default` | any | Default value (injected if not provided) |
| `rename` | string | Expose parameter under different name |
| `description` | string | Override parameter description |

### Behavior

- **hidden + default**: Parameter removed from schema, default always injected
- **default only**: Parameter becomes optional, default used if not provided
- **rename**: LLM sees new name, proxy maps back to original
- **rename + default**: Renamed parameter with default value

---

## Tool Views

Named configurations exposing tool subsets:

```yaml
tool_views:
  myview:
    description: "View description"     # Optional
    exposure_mode: direct               # direct|search|search_per_server
    include_all: false                  # Include all tools from all servers
    tools:                              # Explicit tool selection
      server_name:
        tool_name: {}
    composite_tools:                    # Parallel composition
      # ...
    custom_tools:                       # Python tools
      # ...
    hooks:                              # Pre/post call hooks
      # ...
```

### View Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `description` | string | - | Human-readable description |
| `exposure_mode` | string | `direct` | How tools are exposed |
| `include_all` | boolean | `false` | Include all tools from all servers |
| `tools` | object | - | Server → tool mapping |
| `composite_tools` | object | - | Parallel composition definitions |
| `custom_tools` | list | - | Python tool modules |
| `hooks` | object | - | Pre/post call hooks |

---

## Exposure Modes

Control how tools are presented to clients.

### Direct Mode (Default)

Each tool exposed individually:

```yaml
tool_views:
  myview:
    exposure_mode: direct
    tools:
      server:
        tool_a: {}
        tool_b: {}
```

**Result**: Client sees `tool_a`, `tool_b` as separate tools.

### Search Mode

Two meta-tools for the entire view:

```yaml
tool_views:
  myview:
    exposure_mode: search
    include_all: true
```

**Result**: Client sees:
- `myview_search_tools(query: str)` — Search tools by description
- `myview_call_tool(tool_name: str, arguments: dict)` — Call tool by name

### Search Per Server Mode

Meta-tools per upstream server:

```yaml
tool_views:
  myview:
    exposure_mode: search_per_server
    include_all: true
```

**Result**: For each server (e.g., `filesystem`, `github`):
- `filesystem_search_tools(query: str)`
- `filesystem_call_tool(tool_name: str, arguments: dict)`
- `github_search_tools(query: str)`
- `github_call_tool(tool_name: str, arguments: dict)`

---

## Composite Tools

Create tools that orchestrate multiple upstream tools.

### Parallel Composition

```yaml
tool_views:
  myview:
    composite_tools:
      search_all:
        description: "Search everywhere"
        inputs:
          query:
            type: string
            required: true
            description: "Search query"
          limit:
            type: integer
            required: false
            description: "Max results"
        parallel:
          code:
            tool: github.search_code
            args:
              query: "{inputs.query}"
              per_page: "{inputs.limit|default:10}"
          docs:
            tool: confluence.search
            args:
              query: "{inputs.query}"
```

### Input Types

| Type | Description |
|------|-------------|
| `string` | Text value |
| `integer` | Whole number |
| `number` | Decimal number |
| `boolean` | true/false |
| `object` | JSON object |
| `array` | JSON array |

### Argument Templates

Use `{inputs.name}` to reference input values:

```yaml
args:
  query: "{inputs.query}"                    # Direct reference
  limit: "{inputs.limit|default:10}"         # With default
  path: "/data/{inputs.filename}"            # String interpolation
```

---

## Custom Tools

Python functions with upstream access.

### Definition

```python
# mytools.py
from mcp_proxy.custom_tools import custom_tool, ProxyContext

@custom_tool(
    name="my_tool",
    description="Tool description"
)
async def my_tool(
    query: str,                    # Required parameter
    limit: int = 10,               # Optional with default
    ctx: ProxyContext = None       # Injected context
) -> dict:
    # Call upstream tools
    result = await ctx.call_tool("server.tool", arg1=value)

    # Return result
    return {"data": result}
```

### Registration

```yaml
tool_views:
  myview:
    custom_tools:
      - module: mytools.my_tool
      - module: mytools.another_tool
```

### ProxyContext Methods

| Method | Description |
|--------|-------------|
| `call_tool(name, **kwargs)` | Call upstream tool |
| `get_tool_info(name)` | Get tool schema |
| `list_tools()` | List available tools |

---

## Hooks

Intercept tool calls for logging, validation, or transformation.

### Configuration

```yaml
tool_views:
  myview:
    hooks:
      pre_call: myapp.hooks.before_call
      post_call: myapp.hooks.after_call
    tools:
      server:
        tool: {}
```

### Pre-Call Hook

```python
from mcp_proxy.hooks import HookResult, ToolCallContext

async def before_call(args: dict, context: ToolCallContext) -> HookResult:
    # Modify arguments
    args["modified"] = True
    return HookResult(args=args)

    # Or abort the call
    return HookResult(abort=True, abort_reason="Not allowed")
```

### Post-Call Hook

```python
async def after_call(result, args: dict, context: ToolCallContext) -> HookResult:
    # Transform result
    return HookResult(result={"wrapped": result})

    # Or pass through
    return HookResult(result=result)
```

### ToolCallContext

| Attribute | Type | Description |
|-----------|------|-------------|
| `tool_name` | str | Full tool name (server.tool) |
| `server_name` | str | Upstream server name |
| `view_name` | str | View being called |
| `original_args` | dict | Arguments before modification |

---

## Output Caching

Cache large tool outputs to reduce context usage.

### Global Configuration

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600      # URL expiration (1 hour)
  preview_chars: 500     # Characters shown inline
  min_size: 10000        # Only cache outputs > 10KB

cache_secret: "${CACHE_SECRET}"           # HMAC signing key
cache_base_url: "https://proxy.example.com"  # Base URL for retrieval
```

### Per-Server Override

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [...]
    cache_outputs:
      enabled: true
      min_size: 5000     # Lower threshold for this server
```

### Per-Tool Override

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [...]
    tools:
      read_file:
        cache_output:
          enabled: true
          preview_chars: 1000  # More preview for this tool
```

### Cached Response Format

When output exceeds `min_size`:

```json
{
  "cached": true,
  "token": "abc123def456",
  "retrieve_url": "https://proxy.example.com/cache/abc123def456?expires=1736797800&sig=...",
  "expires_at": "2025-01-13T19:30:00Z",
  "preview": "First 500 characters...",
  "size_bytes": 248000
}
```

### Retrieval Methods

1. **Tool**: Call `retrieve_cached_output(token="abc123def456")`
2. **HTTP**: GET the `retrieve_url` directly
3. **Code**: `requests.get(retrieve_url).text`

---

## Authentication

OAuth 2.1 authentication via OIDC/Auth0.

### Environment Variables

```bash
export FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL="https://tenant.auth0.com/.well-known/openid-configuration"
export FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID="your-client-id"
export FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET="your-client-secret"
export FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE="your-api-audience"
export FASTMCP_SERVER_AUTH_AUTH0_BASE_URL="https://your-proxy-url.com"

# Optional: required scopes (comma-separated)
export FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES="read,write"
```

When these variables are set, the proxy automatically enables OAuth 2.1 with PKCE support.

---

## HTTP Endpoints

When running with `--transport http`:

| Endpoint | Description |
|----------|-------------|
| `/mcp` | Default MCP endpoint (all server tools) |
| `/view/{name}/mcp` | View-specific MCP endpoint |
| `/search/mcp` | Built-in search-per-server view |
| `/views` | List all available views |
| `/views/{name}` | Get view details |
| `/health` | Health check |
| `/cache/{token}` | Retrieve cached output (if caching enabled) |

### Built-in Search Endpoint

`/search/mcp` is a virtual view that exposes all tools using `search_per_server` mode without configuration:

```bash
# Connect to search endpoint
curl http://localhost:8000/search/mcp
```

This provides `{server}_search_tools` and `{server}_call_tool` for each upstream server.

---

## CLI Reference

### Global Options

```bash
mcp-proxy [OPTIONS] COMMAND

Options:
  --config, -c PATH    Configuration file (default: ~/.config/mcp-proxy/config.yaml)
  --env-file PATH      Load environment from file
  --help               Show help
```

### serve

Start the proxy server.

```bash
mcp-proxy serve [OPTIONS]

Options:
  --transport TEXT     Transport type: stdio|http (default: stdio)
  --port INTEGER       HTTP port (default: 8000)
  --host TEXT          HTTP host (default: 0.0.0.0)
```

### validate

Validate configuration file.

```bash
mcp-proxy validate [OPTIONS]

Options:
  --check-connections  Test upstream server connectivity
```

### schema

Show tool schemas.

```bash
mcp-proxy schema [TOOL_NAME]

Arguments:
  TOOL_NAME            Optional: specific tool (server.tool format)

Options:
  --server TEXT        Filter by server
  --json               Output as JSON
```

### call

Call a tool directly (for testing).

```bash
mcp-proxy call TOOL_NAME [OPTIONS]

Arguments:
  TOOL_NAME            Tool to call (server.tool format)

Options:
  --arg KEY=VALUE      Tool argument (repeatable)
```

### config

Show configuration.

```bash
mcp-proxy config [OPTIONS]

Options:
  --resolved           Expand environment variables
```

### init

Generate example files.

```bash
mcp-proxy init TYPE

Arguments:
  TYPE                 File type: config|hooks
```

### server

Server management commands.

```bash
# List servers
mcp-proxy server list [--verbose] [--json]

# Add stdio server
mcp-proxy server add NAME --command CMD [--args ARGS] [--env KEY=VAL]

# Add HTTP server
mcp-proxy server add NAME --url URL [--header KEY=VAL]

# Remove server
mcp-proxy server remove NAME [--force]

# Set tool allowlist
mcp-proxy server set-tools NAME "tool1,tool2,tool3"

# Clear tool filter
mcp-proxy server clear-tools NAME

# Rename tool
mcp-proxy server rename-tool NAME OLD_NAME NEW_NAME

# Set tool description
mcp-proxy server set-tool-description NAME TOOL "Description"

# Configure parameter
mcp-proxy server set-tool-param NAME TOOL PARAM [OPTIONS]
  --hidden             Hide parameter
  --default VALUE      Set default value
  --rename NEW_NAME    Rename parameter
  --description TEXT   Set description
  --clear              Remove configuration
```

### view

View management commands.

```bash
# List views
mcp-proxy view list [--verbose] [--json]

# Create view
mcp-proxy view create NAME [--description TEXT] [--exposure-mode MODE]

# Delete view
mcp-proxy view delete NAME

# Add server to view
mcp-proxy view add-server VIEW SERVER [--tools "t1,t2"] [--all]

# Remove server from view
mcp-proxy view remove-server VIEW SERVER

# Configure tools in view
mcp-proxy view set-tools VIEW SERVER "tool1,tool2"
mcp-proxy view clear-tools VIEW SERVER
mcp-proxy view rename-tool VIEW SERVER OLD_NAME NEW_NAME
mcp-proxy view set-tool-description VIEW SERVER TOOL "Description"
mcp-proxy view set-tool-param VIEW SERVER TOOL PARAM [OPTIONS]
```

---

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
