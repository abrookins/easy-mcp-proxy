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
- [Built-in Tools](#built-in-tools)
- [Hooks](#hooks)
- [Output Caching](#output-caching)
- [Authentication](#authentication)
- [HTTP Endpoints](#http-endpoints)
- [CLI Reference](#cli-reference)

---

## Configuration File

The managed service reads encrypted revisions from `MCP_PROXY_STATE_DIR`.
The [administration guide](user-owned-configuration.md) covers bootstrap,
remote preview/apply, migration, and recovery.

YAML remains the input for offline import and local file commands. Those commands
use `~/.config/mcp-proxy/config.yaml` by default, or a command-level `--config`:

```bash
uv run mcp-proxy validate --config /path/to/config.yaml
```

`serve --config` is rejected. Editing YAML, `.overrides.json`, or using the local
`server`/`view` commands does not update a running managed service. Import with
`users import` while stopped, or use `/config` or `manage` while running.
YAML examples below describe the same fields as the managed JSON editor;
`${VAR}` substitutions apply only to the local file loader.

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

# Safe output handling and caching (enabled by default)
output_cache:
  enabled: true
  ttl_seconds: 3600
  max_inline_tokens: 3000
  token_chars_ratio: 4
  max_inline_chars: 12000
  max_line_chars: 1200
  retrieval_default_line_count: 100
  retrieval_max_line_count: 500
  retrieval_max_chars: 12000
```

---

## Upstream Servers

Changing server commands, arguments, environment, working directories, HTTP
destinations, hooks, or custom Python requires a locally provisioned operator.
New HTTP destinations must use HTTP(S) and have no userinfo, query, or fragment;
put credentials in headers. Operator code runs with the service's OS privileges.

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
    url: "https://api.example.com/mcp/sse"  # Required: upstream MCP endpoint
    headers:                                 # Optional: HTTP headers
      Authorization: "Bearer ${TOKEN}"
    tools:
      tool_name: {}
```

### Environment Variable Expansion

The local YAML loader expands `${VAR_NAME}` from the operator's environment when
inspecting or importing a file:

```yaml
env:
  API_KEY: ${MY_API_KEY}
  DEBUG: "true"
```

Set those variables before running `users import`. The imported values are stored
encrypted. Remote preview/apply rejects `${...}` interpolation; use browser
credential entry or preserve the opaque `{"$secret":"id"}` objects returned by
the service. MCP admin tools reject inline secrets.

`serve --env-file .env` loads **service bootstrap** settings (OAuth, state path,
listener, or stdio owner), not live upstream configuration. The default file is
`.env`; importing a YAML file does not implicitly load that file.

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

Named configurations exposing tool subsets within one owner. A client must also
have an explicit grant for the selected view. `admin`, `search`, and `_search`
are reserved names; use a name such as `full` for a full-access upstream view.
`/view/admin/mcp` is reserved for proxy administration.

```yaml
tool_views:
  myview:
    description: "View description"     # Optional
    exposure_mode: direct               # direct|search|search_per_server
    include_all: false                  # Include all tools from all servers
    include_all_servers: [memory]       # Include all tools from selected servers
    exclude_servers: []                 # Servers to omit from this view
    tools:                              # Explicit tool selection
      server_name:
        tool_name: {}
    composite_tools:                    # Concurrent composition
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
| `include_all_servers` | list | `[]` | Include every tool from selected servers without maintaining an allowlist |
| `exclude_servers` | list | `[]` | Servers to omit from the view |
| `tools` | object | - | Server → tool mapping |
| `composite_tools` | object | - | Concurrent composition definitions |
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

Three meta-tools for the entire view:

```yaml
tool_views:
  myview:
    exposure_mode: search
    include_all: true
```

**Result**: Client sees:
- `myview_search_tools(query: str)` — Search tools by description
- `myview_describe_tool(tool_name: str)` — Inspect one exact exposed schema
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
- `filesystem_describe_tool(tool_name: str)`
- `filesystem_call_tool(tool_name: str, arguments: dict)`
- `github_search_tools(query: str)`
- `github_describe_tool(tool_name: str)`
- `github_call_tool(tool_name: str, arguments: dict)`

---

## Composite Tools

Create tools that orchestrate multiple upstream tools.

### Concurrent Composition

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

## Built-in Tools

Easy MCP Proxy includes several built-in custom tools that can be added to any view.

### Code Sandbox

Docker-based code execution sandbox for running code in isolated containers. Works on Mac (via Docker Desktop/OrbStack) and Linux.

**Requirements**: Docker must be installed and running.

#### Tools

| Tool | Description |
|------|-------------|
| `run_code_sandbox` | Execute code in an isolated container (one-shot) |
| `sandbox_session_start` | Start a persistent sandbox session |
| `sandbox_session_exec` | Execute code in an existing session |
| `sandbox_session_stop` | Stop and remove a session |
| `sandbox_session_list` | List all active sessions |

#### Configuration

```yaml
tool_views:
  default:
    custom_tools:
      - module: mcp_proxy.tools.sandbox.run_code_sandbox
      - module: mcp_proxy.tools.sandbox.sandbox_session_start
      - module: mcp_proxy.tools.sandbox.sandbox_session_exec
      - module: mcp_proxy.tools.sandbox.sandbox_session_stop
      - module: mcp_proxy.tools.sandbox.sandbox_session_list
```

#### run_code_sandbox Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | (required) | Code to execute |
| `language` | string | `"python"` | Language: `python`, `node`, `bash` |
| `timeout` | int | `30` | Execution timeout in seconds |
| `isolation_level` | string | `"standard"` | Security level: `minimal`, `standard`, `secure` |
| `memory_limit` | string | `"256m"` | Memory limit (e.g., `"512m"`, `"1g"`) |
| `cpu_limit` | float | `1.0` | CPU limit (e.g., `0.5` for half a core) |
| `packages` | list | `null` | Packages to install before execution |

#### Isolation Levels

| Level | Network | Read-only FS | Privilege Restrictions |
|-------|---------|--------------|------------------------|
| `minimal` | ✓ Allowed | No | No |
| `standard` | ✗ Blocked | Yes | Yes |
| `secure` | ✗ Blocked | Yes | Full hardening |

#### Security Features

- **Image Allowlist**: Only pre-approved Docker images can be used
- **Package Validation**: Package names are validated to prevent command injection
- **Resource Caps**: Memory, CPU, and timeout are capped to prevent DoS
- **Session Limits**: Maximum 10 concurrent sessions
- **Container Hardening**: Sessions use `--security-opt no-new-privileges --cap-drop ALL`

#### Examples

```python
# Basic Python execution
run_code_sandbox(code="print('hello world')")

# Install packages and make network requests
run_code_sandbox(
    code="import requests; print(requests.get('https://api.github.com').status_code)",
    packages=["requests"],
    isolation_level="minimal"  # Network access required
)

# Persistent session for multi-step work
session = sandbox_session_start(language="python", packages=["pandas"])
sandbox_session_exec(session_id=session["session_id"], code="import pandas as pd")
sandbox_session_exec(session_id=session["session_id"], code="df = pd.DataFrame({'a': [1,2,3]})")
sandbox_session_exec(session_id=session["session_id"], code="print(df.describe())")
sandbox_session_stop(session_id=session["session_id"])
```

### Code Quality Analysis

Analyze code quality using the MFCQI tool.

```yaml
tool_views:
  default:
    custom_tools:
      - module: mcp_proxy.tools.mfcqi.analyze_code_quality
```

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

Safe output handling is enabled by default. After an upstream MCP server
responds, the proxy measures the visible result. Results that exceed the inline
token/character budget or contain overlong lines are cached and replaced with a
bounded preview plus navigation metadata. This protects every proxied call path,
including direct tools, view calls, search-mode `*_call_tool` wrappers, custom
tools, composite tools, and the virtual `/search/mcp` view.

### Global Configuration

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600
  max_inline_tokens: 3000
  token_chars_ratio: 4
  max_inline_chars: 12000
  max_line_chars: 1200
  retrieval_default_line_count: 100
  retrieval_max_line_count: 500
  retrieval_max_chars: 12000
  preview_chars: 500     # Compatibility cap for older configs
  min_size: 10000        # Optional extra cache threshold
```

If `output_cache` is omitted, the proxy uses the safe defaults above. Set
`enabled: false` only to opt out explicitly. The managed runtime derives signing
keys per user and view from persistent state and generates retrieval URLs at
`/view/VIEW/cache/TOKEN`. It rejects user-supplied `cache_secret` and
`cache_base_url`. Offline import strips those legacy settings; old cache links
do not migrate.

The low-level `MCPProxy(config)` library still accepts those two settings and
uses a process-local key when none is provided. That library behavior does not
define authentication or ownership for the managed service.

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
          max_inline_tokens: 4000
          preview_chars: 1000  # Compatibility cap for this tool
```

### Cached Response Format

When output exceeds any active limit:

```json
{
  "cached": true,
  "cache_id": "abc123def456",
  "token": "abc123def456",
  "truncated": true,
  "truncation_reasons": ["estimated_tokens", "max_line_chars"],
  "retrieve_url": "https://proxy.example.com/view/default/cache/abc123def456?expires=1736797800&sig=...",
  "expires_at": "2026-07-31T19:30:00Z",
  "preview": "Bounded preview...",
  "size_bytes": 248000,
  "original": {
    "bytes": 248000,
    "chars": 248000,
    "estimated_tokens": 62000,
    "lines": 1,
    "longest_line_chars": 248000
  },
  "returned": {
    "bytes": 1200,
    "chars": 1200,
    "estimated_tokens": 300,
    "lines": 1,
    "longest_line_chars": 1200
  },
  "limits": {
    "max_inline_tokens": 3000,
    "max_inline_chars": 12000,
    "max_line_chars": 1200
  },
  "navigation": {
    "preview_tool": "preview_cached_output",
    "range_tool": "range_cached_output",
    "query_tool": "query_cached_output",
    "next_line_offset": null,
    "next_char_offset": 1200
  }
}
```

### Retrieval Methods

1. **Default tool retrieval**: Call `retrieve_cached_output(token="abc123def456")`
   for a bounded payload.
2. **Line window**: Call `preview_cached_output(token="abc123def456",
   line_offset=200, line_count=100)`
3. **Character window**: Call `range_cached_output(token="abc123def456",
   char_offset=1200, char_count=12000)` for minified or single-line content.
4. **JSON query**: Call `query_cached_output(token="abc123def456",
   jmespath_expression="items[].title")`
5. **HTTP bounded retrieval**: GET the signed `retrieve_url` with OAuth for the
   same owner and a grant for that view, or an authorized browser session.
6. **HTTP filters**: Append `line_offset`, `line_count`, `char_offset`,
   `char_count`, or `jmespath` query parameters.
7. **Explicit full download**: Append `download=1` or `full=1` to the signed
   HTTP URL for code or out-of-context processing.

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

# Optional: disable Client ID Metadata Documents and require Dynamic Client Registration
export MCP_PROXY_AUTH_ENABLE_CIMD="false"
```

The managed HTTP service requires all five provider variables and
`MCP_PROXY_STATE_DIR`. OAuth admission alone does not provision an owner or grant
access. The verified issuer/subject must be provisioned locally, and each
**downstream MCP client ID** must receive explicit view grants. Admin access is
an additional grant; changing host capabilities also requires operator status.

Supply the client secret through a private environment or secret manager. The
example above shows variable names with placeholders, not real credentials.
Client ID Metadata Document support is enabled by default; set
`MCP_PROXY_AUTH_ENABLE_CIMD=false` to require Dynamic Client Registration.
Optional admission controls are `MCP_PROXY_AUTH_ALLOWED_EMAILS` (comma-separated)
and `MCP_PROXY_AUTH_REQUIRE_EMAIL_VERIFIED`; neither replaces ownership/grants.
User-bound API keys are also supported through explicit local issuance/import;
unbound environment tokens and unauthenticated HTTP are rejected. See
[API key commands and permissions](user-owned-configuration.md#user-bound-api-keys).

Keys and encrypted OAuth state persist in the state directory. Existing
installations must [import compatible OAuth state](user-owned-configuration.md#migrate-an-existing-installation)
to preserve registrations and tokens. Creating a fresh directory does not migrate
sessions. Browser administrators log in once after the upgrade; managed browser
sessions survive later restarts.

---

## HTTP Endpoints

When running with `--transport http`, the main routes are:

| Endpoint | Description / access |
|----------|----------------------|
| `/mcp` | Authenticated owner's default view; explicit view grant |
| `/view/{name}/mcp` | That owner's named view; explicit view grant |
| `/search/mcp` | That owner's upstream tools through search helpers; `search` grant |
| `/view/admin/mcp` | Proxy admin tools and MCP App resource; admin and `admin` view grants |
| `/views` | Names granted to the authenticated client |
| `/health` | Public process health check |
| `/config` | Browser administration; browser login and admin grant |
| `/config/login`, `/config/login/callback` | Browser OAuth flow |
| `/config/logout` | POST-only browser logout; same-origin check |
| `/config/api/identity` | Verified owner/client identity; no provisioning or grant side effect |
| `/config/api/{action}` | Management operations listed below; admin grant |
| `/view/{view}/cache/{token}` | Signed cache retrieval plus same-owner/view authorization |

Management GET actions are `config`, `history`, and `status`. POST actions are
`preview`, `probe`, `apply`, and `rollback`. See the
[request/response contract](user-owned-configuration.md#browser-api-cli-and-mcp).
The legacy `/config/api/tools`, restart/PUT APIs, `/views/{name}`, and unscoped
`/cache/{token}` routes are not exposed by the managed gateway.

HTTP cache retrieval returns bounded metadata by default. `download=1` or `full=1`
requests full content. A signed link alone is insufficient: OAuth or a browser
session must also identify the same owner with access to that view. Do not put
OAuth tokens in query strings.

### Built-in Search Endpoint

Connect an OAuth MCP client to `/search/mcp` after granting it `search`. This
virtual view exposes that owner's upstream tools using `search_per_server` mode,
with `{server}_search_tools`, `{server}_describe_tool`, and `{server}_call_tool`.
A narrow default view does not restrict this separate search view; grant it only
when the client should discover all of that owner's upstream tools.

### Administration UI and client refresh

`/view/admin/mcp` exposes typed configuration tools and the proxy-owned MCP App.
Hosts without embedded UI support can use those tools or the `/config` browser
link. Forwarding third-party upstream Apps is deferred. Actual Claude/ChatGPT
account and native-device behavior remains [unverified](specs/remote-configuration-acceptance.md#host-compatibility-and-remaining-external-checks).

An MCP apply sends a tool-list notification on its active request stream. Browser
edits cannot broadcast to idle stateless clients; refresh the client's tool list
if needed. Live updates do not restart the process. Calls using replaced
connections may fail if they exceed the 10-second drain deadline.

---

## CLI Reference

### Command Options

`mcp-proxy --help` lists commands. Options belong to the command that accepts
them: `--config` is for local file commands, `--env-file` is for `serve`,
`--state-dir` is for `users`, and `--url` is for `manage`.

### serve

Start one managed runtime against a provisioned state directory:

```bash
uv run mcp-proxy serve [OPTIONS]

Options:
  --transport, -t TEXT   stdio|http (default: stdio)
  --port, -p INTEGER     HTTP port (default: 8000)
  --env-file, -e PATH    Bootstrap environment file (default: .env)
  --access-log / --no-access-log   HTTP access logging (default: enabled)
```

Set `MCP_PROXY_HOST` to change the HTTP listener (default: `127.0.0.1`); there is
no `--host` flag. HTTP needs OAuth and `MCP_PROXY_STATE_DIR`. Stdio also needs
`MCP_PROXY_OWNER_ISSUER`, `MCP_PROXY_OWNER_SUBJECT`, and a `mcp-proxy-local`
grant. It serves the owner's default view. Only one runtime per state directory
is supported, including across HTTP and stdio.

The retained `--config` option raises migration guidance when supplied.
`--debug` remains accepted for compatibility but the managed serve path does not
use it. For file logging, set `MCP_PROXY_LOG_FILE` and `MCP_PROXY_LOG_LEVEL`.

### users

Local operator commands for ownership, grants, and offline imports:

```bash
uv run mcp-proxy users --state-dir /PRIVATE/STATE provision \
  --issuer 'https://YOUR-ISSUER/' --subject 'VERIFIED-SUBJECT' --operator
uv run mcp-proxy users --state-dir /PRIVATE/STATE grant USER_ID \
  --client CLIENT_ID --view default
uv run mcp-proxy users --state-dir /PRIVATE/STATE revoke USER_ID --client CLIENT_ID
```

`MCP_PROXY_STATE_DIR` can supply `--state-dir`. `grant` accepts repeated `--view`
and optional `--admin`; omitting `--view` grants `default`. Re-granting replaces
that client's grant, so include all views it should retain. `'*'` grants all
views, but the dedicated admin endpoint still needs `--admin`.

`users import --issuer ... --subject ... --config FILE` imports YAML for a
provisioned owner with a local admin grant. `users import-oauth --source DIR`
migrates compatible legacy OAuth storage. Both are dry runs unless `--apply` is
provided; stop the runtime first. See the [migration sequence](user-owned-configuration.md#migrate-an-existing-installation).

### manage

Use OAuth to manage the logged-in user's remote configuration:

```bash
uv run mcp-proxy manage --url https://proxy.example.org identity
uv run mcp-proxy manage --url https://proxy.example.org config
uv run mcp-proxy manage --url https://proxy.example.org preview --input candidate.json
uv run mcp-proxy manage --url https://proxy.example.org apply --input apply.json
```

Actions: `identity`, `config`, `history`, `status`, `preview`, `probe`, `apply`,
and `rollback`. Mutations require a JSON `--input FILE` or `--input -`; read-only
actions reject it. `MCP_PROXY_URL` can supply `--url`. OAuth credentials are
stored encrypted in `~/.local/state/mcp-proxy-client`; override with
`--credential-dir`. Automation may set `MCP_PROXY_ACCESS_TOKEN` to a current
OAuth access token or a user-bound API key with an admin grant. There is no
secret/token command-line option.

### Local file commands

The commands below inspect or edit YAML, not the managed store. They use
`~/.config/mcp-proxy/config.yaml` unless given `--config PATH`. Inspection may
start configured subprocesses or connect to upstreams. Use only trusted files;
local tool calls bypass the managed gateway's user grants.

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
  --view TEXT          Inspect canonical metadata for one exposed view
  --json               Output as JSON
```

`SERVER.TOOL` without `--view` shows raw upstream metadata. With `--view`, the
tool name is the final exposed name and output reflects renames, hidden
parameters, defaults, and description overrides. See [Tool Discovery,
Inspection, and Safe Calls](tool-discovery.md) for local and live examples.

### tools and servers

```bash
uv run mcp-proxy servers --config config.yaml
uv run mcp-proxy tools --config config.yaml --view default --verbose --json
```

`servers` lists names in the file. `tools` without a view/verbose/JSON option
lists configured names without connecting. The richer forms discover upstream
tools and return canonical metadata after view transformations. `--server NAME`
filters the inventory.

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
│  │  │  readonly   │  │   search    │  │   all-tools     │    │  │
│  │  │  - fs read  │  │ - search_*  │  │ - include_all   │    │  │
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
│  │  │  filesystem  │  │   github     │  │    zapier    │     │  │
│  │  │   (stdio)    │  │   (stdio)    │  │   (http)     │     │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```
