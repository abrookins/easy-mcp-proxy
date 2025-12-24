# ADR-002: Implementation Changes from Initial Design

## Status

Accepted

## Context

The initial design ([001-initial-design.md](./001-initial-design.md)) outlined a comprehensive vision for an MCP proxy with tool views. During implementation, several design decisions were refined based on practical constraints and real-world usage patterns.

## Key Changes

### 1. Tool Registration on Upstream Servers

**Original Design**: Tool configurations lived only in `tool_views`.

**Implementation**: Tools can be configured directly on `mcp_servers` with a `tools` key. This allows filtering and description overrides at the server level, independent of views.

```yaml
mcp_servers:
  github:
    url: "https://api.githubcopilot.com/mcp/"
    tools:  # Filter at server level
      search_code: {}
      search_issues:
        description: "Search issues. {original}"
```

**Rationale**: Many use cases require simple tool filtering without creating explicit views. Server-level configuration is simpler for basic scenarios.

### 2. Search Mode Implementation

**Original Design**: Proposed `{view_name}_search_tools` meta-tool only.

**Implementation**: Implemented both `{view_name}_search_tools` AND `{view_name}_call_tool`. The search tool returns tool metadata; the call tool executes found tools by name.

**Rationale**: LLMs need a way to execute tools discovered via search. The two-step pattern (search → call) matches how agents reason about available tools.

### 3. HTTP Multi-View Routing

**Original Design**: Did not specify HTTP routing for multiple views.

**Implementation**: Starlette-based ASGI app with path-based view routing:
- `/mcp` - Default endpoint (all server tools)
- `/view/{name}/mcp` - View-specific MCP endpoints
- `/views` - List available views
- `/views/{name}` - View metadata
- `/health` - Health check

**Rationale**: HTTP deployments need a way to expose multiple views from a single server with proper endpoint discovery.

### 4. Simplified Hook Signatures

**Original Design**: Hooks received `ToolCallContext` as first argument.

**Implementation**: Pre-call hooks receive `(args, context)`, post-call hooks receive `(result, args, context)`.

```python
async def pre_call(args: dict, context: ToolCallContext) -> HookResult:
    ...

async def post_call(result, args: dict, context: ToolCallContext) -> HookResult:
    ...
```

**Rationale**: Putting the mutable data first makes the common case (modifying args/result) more ergonomic.

### 5. CLI for Configuration Management

**Original Design**: Proposed basic CLI for inspection and serving.

**Implementation**: Full configuration management CLI with subcommand groups:
- `mcp-proxy server add/remove/list/set-tools`
- `mcp-proxy view create/delete/add-server/set-tools`
- `mcp-proxy schema/validate/serve/call`

**Rationale**: Managing YAML by hand is error-prone. CLI commands provide validated, atomic configuration changes.

### 6. Tool Call Wrapper Pattern

**Original Design**: Proposed wrapping tools at registration time.

**Implementation**: Tools registered with generic `arguments: dict` parameter, routing through `ToolView.call_tool()` at execution time.

**Rationale**: FastMCP doesn't support `**kwargs` in tool signatures. Using an explicit `arguments` dict provides a consistent interface while maintaining runtime flexibility.

### 7. Composite Tool Input Resolution

**Original Design**: `{inputs.X}` template syntax for parallel tool arguments.

**Implementation**: Implemented as designed, with the addition of error handling that captures per-step failures without aborting the entire parallel execution.

```yaml
composite_tools:
  search_all:
    parallel:
      code: { tool: github.search_code, args: { query: "{inputs.query}" } }
      issues: { tool: github.search_issues, args: { query: "{inputs.query}" } }
```

If one step fails, results include `{"step_name": {"error": "..."}}` while other steps succeed.

## Features Not Yet Implemented

The following features from the initial design are deferred:

1. **Chain composition** (`chain:` in composite_tools) - Only parallel supported
2. **Authentication hooks** - Hook system exists but no built-in auth patterns
3. **Per-view access control lists** - No authorization layer yet

## Consequences

- Server-level tool config reduces boilerplate for simple filtering
- HTTP routing enables single-deployment multi-tenant scenarios
- CLI management reduces configuration errors
- Generic argument wrapper trades static typing for runtime flexibility
- Error isolation in parallel tools improves resilience

