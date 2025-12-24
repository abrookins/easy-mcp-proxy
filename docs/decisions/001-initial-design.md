# MCP Tool View Proxy Design

## Overview

This document describes the design for an MCP proxy server built with FastMCP 2 that provides **tool views** - named configurations that expose filtered subsets of tools from upstream MCP servers with optional transformations and hooks.

## Core Concepts

### Tool Views

A **tool view** is a named configuration that:
1. Aggregates tools from one or more upstream MCP servers
2. Filters which tools are exposed to callers
3. Optionally transforms tool descriptions (using `{original}` placeholder)
4. Attaches pre/post-call hooks for custom logic
5. Can expose tools directly OR via a single "tool search" meta-tool

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Proxy Server                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                      Tool Views                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐    │  │
│  │  │ redis-expert│  │   github    │  │ code-assistant  │    │  │
│  │  │  - search   │  │ - search_*  │  │ - all tools     │    │  │
│  │  │  - memory   │  │ - issue_*   │  │ - search mode   │    │  │
│  │  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘    │  │
│  └─────────┼────────────────┼──────────────────┼─────────────┘  │
│            │                │                  │                 │
│  ┌─────────▼────────────────▼──────────────────▼─────────────┐  │
│  │                    Hook System                             │  │
│  │  pre_call(tool, args) → modified_args                      │  │
│  │  post_call(tool, args, result) → modified_result           │  │
│  └─────────┬────────────────┬──────────────────┬─────────────┘  │
│            │                │                  │                 │
│  ┌─────────▼────────────────▼──────────────────▼─────────────┐  │
│  │                 Upstream MCP Clients                       │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │  │
│  │  │redis-memory  │  │   github     │  │  filesystem  │     │  │
│  │  │   server     │  │    MCP       │  │     MCP      │     │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration Schema

```yaml
# config.yaml
mcp_servers:
  # Upstream server definitions
  redis-memory-server:
    command: uv
    args: [tool, run, --from, agent-memory-server, agent-memory, mcp]
    env:
      REDIS_URL: redis://localhost:6399

  github:
    url: "https://api.githubcopilot.com/mcp/"
    headers:
      Authorization: "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"

tool_views:
  # View 1: Redis Expert - exposes specific tools with custom descriptions
  redis-expert:
    description: "Tools for Redis memory and knowledge operations"
    exposure_mode: direct  # or "search"
    tools:
      redis-memory-server:
        search_long_term_memory:
          name: search_knowledge  # Rename for clarity
          description: |
            Search the Redis knowledge base for relevant information.
            {original}
        create_long_term_memories: {}
        memory_prompt: {}
    hooks:
      pre_call: hooks.redis_expert.pre_call
      post_call: hooks.redis_expert.post_call

  # View 2: GitHub - filtered subset with search mode
  github:
    description: "GitHub code and issue search tools"
    exposure_mode: search  # Exposes single search_tools meta-tool
    tools:
      github:
        search_code: {}
        search_issues: {}
        search_pull_requests: {}
        issue_read: {}
        pull_request_read: {}
    hooks:
      pre_call: hooks.github.validate_auth

  # View 3: Full access view
  all-tools:
    description: "All available tools from all servers"
    exposure_mode: direct
    include_all: true  # Include all tools from all servers
```

## Python Implementation Structure

```
mcp_proxy/
├── __init__.py
├── main.py              # Entry point
├── config.py            # Configuration loading and validation
├── models.py            # Pydantic models for config
├── proxy.py             # Main proxy server implementation
├── views.py             # ToolView class and management
├── hooks.py             # Hook system base classes
└── search.py            # Tool search meta-tool implementation
```

## Core Components

### 1. Configuration Models (`models.py`)

```python
from pydantic import BaseModel
from typing import Literal

class ToolConfig(BaseModel):
    """Configuration for a single tool within a view."""
    name: str | None = None  # Rename the tool
    description: str | None = None  # Supports {original} placeholder
    enabled: bool = True

class ServerToolsConfig(BaseModel):
    """Tools to include from a specific upstream server."""
    __root__: dict[str, ToolConfig]

class HooksConfig(BaseModel):
    """Hook function references for a view."""
    pre_call: str | None = None   # e.g., "hooks.redis.pre_call"
    post_call: str | None = None  # e.g., "hooks.redis.post_call"

class ToolViewConfig(BaseModel):
    """Configuration for a tool view."""
    description: str
    exposure_mode: Literal["direct", "search"] = "direct"
    tools: dict[str, dict[str, ToolConfig]] = {}  # server_name -> tool_name -> config
    include_all: bool = False
    hooks: HooksConfig | None = None

class UpstreamServerConfig(BaseModel):
    """Configuration for an upstream MCP server."""
    # For local command execution
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    # For remote HTTP servers
    url: str | None = None
    headers: dict[str, str] = {}

class ProxyConfig(BaseModel):
    """Root configuration for the MCP proxy."""
    mcp_servers: dict[str, UpstreamServerConfig]
    tool_views: dict[str, ToolViewConfig]
```

### 2. Hook System (`hooks.py`)

```python
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass

@dataclass
class ToolCallContext:
    """Context passed to hooks."""
    view_name: str
    tool_name: str
    upstream_server: str
    # Future: auth context, request metadata, etc.

class HookResult:
    """Result from a hook execution."""
    def __init__(
        self,
        args: dict[str, Any] | None = None,
        result: Any = None,
        abort: bool = False,
        abort_reason: str | None = None
    ):
        self.args = args
        self.result = result
        self.abort = abort
        self.abort_reason = abort_reason

# Hook function signatures
PreCallHook = Callable[[ToolCallContext, dict[str, Any]], Awaitable[HookResult]]
PostCallHook = Callable[[ToolCallContext, dict[str, Any], Any], Awaitable[HookResult]]

async def load_hook(hook_path: str) -> Callable:
    """Dynamically load a hook function from a dotted path."""
    module_path, func_name = hook_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)
```

### 3. Tool View Manager (`views.py`)

```python
from fastmcp import FastMCP, Tool
from fastmcp.tools import Tool as ToolType

class ToolView:
    """Manages a single tool view."""

    def __init__(
        self,
        name: str,
        config: ToolViewConfig,
        upstream_clients: dict[str, Client]
    ):
        self.name = name
        self.config = config
        self.upstream_clients = upstream_clients
        self.tools: dict[str, ToolType] = {}
        self.pre_hook: PreCallHook | None = None
        self.post_hook: PostCallHook | None = None

    async def initialize(self):
        """Load tools from upstream servers and apply transformations."""
        await self._load_hooks()
        await self._load_tools()

    async def _load_tools(self):
        """Fetch and transform tools from upstream servers."""
        for server_name, tool_configs in self.config.tools.items():
            client = self.upstream_clients[server_name]
            upstream_tools = await client.list_tools()

            for tool in upstream_tools:
                if tool.name in tool_configs:
                    tool_config = tool_configs[tool.name]
                    transformed = self._transform_tool(tool, tool_config)
                    self.tools[tool.name] = transformed

    def _transform_tool(self, tool: ToolType, config: ToolConfig) -> ToolType:
        """Apply name/description transformations."""
        kwargs = {}

        if config.name:
            kwargs["name"] = config.name

        if config.description:
            kwargs["description"] = config.description.replace(
                "{original}", tool.description or ""
            )

        if kwargs:
            return Tool.from_tool(tool, **kwargs)
        return tool

    async def call_tool(self, tool_name: str, args: dict) -> Any:
        """Execute a tool with pre/post hooks."""
        context = ToolCallContext(
            view_name=self.name,
            tool_name=tool_name,
            upstream_server=self._get_server_for_tool(tool_name)
        )

        # Pre-call hook
        if self.pre_hook:
            result = await self.pre_hook(context, args)
            if result.abort:
                raise ToolCallAborted(result.abort_reason)
            if result.args:
                args = result.args

        # Execute upstream tool
        client = self.upstream_clients[context.upstream_server]
        result = await client.call_tool(tool_name, args)

        # Post-call hook
        if self.post_hook:
            hook_result = await self.post_hook(context, args, result)
            if hook_result.result is not None:
                result = hook_result.result

        return result
```


### 4. Tool Search Meta-Tool (`search.py`)

When `exposure_mode: search` is set, the view exposes a single `search_tools` meta-tool instead of individual tools:

```python
from fastmcp import FastMCP

class ToolSearcher:
    """Provides tool search functionality for a view."""

    def __init__(self, view: ToolView):
        self.view = view

    def create_search_tool(self) -> Tool:
        """Create the search_tools meta-tool for this view."""

        @tool(
            name=f"{self.view.name}_search_tools",
            description=f"Search for available tools in the {self.view.name} view. "
                        f"Returns matching tools with their descriptions and parameters."
        )
        async def search_tools(
            query: str = "",
            limit: int = 10
        ) -> list[dict]:
            """
            Search for tools matching the query.

            Args:
                query: Search term to filter tools by name or description
                limit: Maximum number of results to return

            Returns:
                List of matching tools with name, description, and parameters
            """
            results = []
            for name, tool in self.view.tools.items():
                if query.lower() in name.lower() or \
                   query.lower() in (tool.description or "").lower():
                    results.append({
                        "name": name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    })
                if len(results) >= limit:
                    break
            return results

        return search_tools
```

### 5. Main Proxy Server (`proxy.py`)

```python
from fastmcp import FastMCP, Client
from fastmcp.server.proxy import ProxyClient

class MCPProxy:
    """Main MCP proxy server with tool views."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self.server = FastMCP("MCP Tool View Proxy")
        self.upstream_clients: dict[str, Client] = {}
        self.views: dict[str, ToolView] = {}

    async def initialize(self):
        """Initialize upstream connections and tool views."""
        # Connect to upstream servers
        for name, server_config in self.config.mcp_servers.items():
            client = self._create_client(name, server_config)
            self.upstream_clients[name] = client

        # Initialize tool views
        for view_name, view_config in self.config.tool_views.items():
            view = ToolView(view_name, view_config, self.upstream_clients)
            await view.initialize()
            self.views[view_name] = view

            # Register tools based on exposure mode
            if view_config.exposure_mode == "direct":
                self._register_direct_tools(view)
            else:
                self._register_search_tool(view)

    def _create_client(self, name: str, config: UpstreamServerConfig) -> Client:
        """Create a client for an upstream server."""
        if config.url:
            # Remote HTTP server
            return ProxyClient(config.url, headers=config.headers)
        else:
            # Local command execution
            return ProxyClient(
                command=config.command,
                args=config.args,
                env=config.env
            )

    def _register_direct_tools(self, view: ToolView):
        """Register view tools directly on the proxy server."""
        for tool_name, tool in view.tools.items():
            # Create wrapped tool that goes through hooks
            wrapped = self._wrap_tool_with_hooks(view, tool)
            self.server.add_tool(wrapped)

    def _register_search_tool(self, view: ToolView):
        """Register the search meta-tool for a view."""
        searcher = ToolSearcher(view)
        search_tool = searcher.create_search_tool()
        self.server.add_tool(search_tool)

    def _wrap_tool_with_hooks(self, view: ToolView, tool: Tool) -> Tool:
        """Wrap a tool to execute through the view's hook system."""
        async def wrapped_fn(**kwargs):
            return await view.call_tool(tool.name, kwargs)

        return Tool.from_tool(
            tool,
            transform_fn=wrapped_fn
        )

    def run(self, transport: str = "stdio", **kwargs):
        """Run the proxy server."""
        self.server.run(transport=transport, **kwargs)
```

## Exposure Modes

### Direct Mode (`exposure_mode: direct`)

Tools are exposed directly to callers with their (optionally transformed) names and descriptions:

```
Caller → Proxy → search_long_term_memory → Upstream Server
```

### Search Mode (`exposure_mode: search`)

A single `{view_name}_search_tools` meta-tool is exposed. Callers first search for tools, then call them by name:

```
Caller → Proxy → github_search_tools("code search") → Returns tool list
Caller → Proxy → github_call_tool("search_code", {...}) → Upstream Server
```

This mode is useful when a view contains many tools and you want to reduce cognitive load on the LLM.

## Hook System Design

### Pre-Call Hooks

Execute before the upstream tool is called. Can:
- Modify arguments
- Abort the call (for auth, rate limiting, validation)
- Add logging/metrics

```python
# hooks/redis_expert.py
async def pre_call(context: ToolCallContext, args: dict) -> HookResult:
    # Example: Add user context to all memory operations
    if "user_id" not in args:
        args["user_id"] = get_current_user_id()
    return HookResult(args=args)
```

### Post-Call Hooks

Execute after the upstream tool returns. Can:
- Transform results
- Add metadata
- Log outcomes

```python
async def post_call(context: ToolCallContext, args: dict, result: Any) -> HookResult:
    # Example: Redact sensitive data from results
    if isinstance(result, dict) and "api_key" in result:
        result["api_key"] = "***REDACTED***"
    return HookResult(result=result)
```

## Authentication Considerations

The hook system provides natural extension points for authentication:

```python
# hooks/auth.py
async def require_auth(context: ToolCallContext, args: dict) -> HookResult:
    """Pre-call hook that validates authentication."""
    auth_token = get_auth_from_context()  # Implementation TBD

    if not auth_token:
        return HookResult(abort=True, abort_reason="Authentication required")

    if not validate_token(auth_token):
        return HookResult(abort=True, abort_reason="Invalid token")

    # Optionally inject user info into args
    args["_auth_user"] = decode_token(auth_token)
    return HookResult(args=args)
```

Future authentication mechanisms could include:
- Bearer token validation in pre-call hooks
- OAuth2 integration
- API key management
- Per-view access control lists

## Usage Example

```python
# main.py
import asyncio
from mcp_proxy import MCPProxy, load_config

async def main():
    config = load_config("config.yaml")
    proxy = MCPProxy(config)
    await proxy.initialize()
    proxy.run(transport="stdio")

if __name__ == "__main__":
    asyncio.run(main())
```

## Advanced Tool Composition

### Parallel Tools (Fan-out)

Run multiple upstream tools simultaneously and collect all results:

```yaml
tool_views:
  unified-search:
    composite_tools:
      search_everywhere:
        description: "Search all sources in parallel"
        inputs:
          query: { type: string, required: true }
        parallel:
          knowledge:
            tool: redis-memory-server.search_long_term_memory
            args: { text: "{inputs.query}" }
          code:
            tool: github.search_code
            args: { query: "{inputs.query}" }
          issues:
            tool: github.search_issues
            args: { query: "{inputs.query}" }
        # Returns: { knowledge: [...], code: [...], issues: [...] }
```

Implementation:

```python
class ParallelTool:
    """Execute multiple tools in parallel, return combined results."""

    async def execute(self, inputs: dict, context: ToolCallContext) -> dict:
        tasks = {}
        for name, step in self.parallel_steps.items():
            resolved_args = self._resolve_templates(step.args, inputs)
            tasks[name] = asyncio.create_task(
                self._call_tool(step.tool, resolved_args)
            )

        results = {}
        for name, task in tasks.items():
            results[name] = await task
        return results
```

### Custom Tools (Python-Defined)

For full control over composition logic, define tools in Python:

```python
# hooks/custom_tools.py
from mcp_proxy import custom_tool, ProxyContext

@custom_tool(
    name="contextual_code_search",
    description="Search code with knowledge base context"
)
async def contextual_code_search(
    query: str,
    ctx: ProxyContext  # Injected automatically
) -> dict:
    """
    Custom tool with full control over:
    - Which upstream tools to call
    - How to transform data between calls
    - Error handling and fallbacks
    """
    # Call upstream tools
    kb_results = await ctx.call_tool(
        "redis-memory-server.search_long_term_memory",
        text=query
    )

    # YOUR transformation logic
    keywords = extract_relevant_terms(kb_results)
    enriched_query = f"{query} {' '.join(keywords)}"

    # Call another tool with transformed input
    code_results = await ctx.call_tool(
        "github.search_code",
        query=enriched_query
    )

    # Return combined/processed results
    return {
        "query": query,
        "enriched_query": enriched_query,
        "knowledge_context": summarize(kb_results),
        "code_matches": code_results
    }
```

Register in config:

```yaml
tool_views:
  smart-search:
    custom_tools:
      - module: hooks.custom_tools.contextual_code_search
      - module: hooks.custom_tools.another_custom_tool
```

### Mixed Composition Example

Combine parallel, chains, and custom tools:

```yaml
tool_views:
  expert-assistant:
    description: "AI coding assistant tools"

    # Direct upstream tools (filtered)
    tools:
      github:
        create_issue: {}
        create_pull_request: {}

    # Parallel composition
    composite_tools:
      search_all:
        parallel:
          memory: { tool: redis-memory-server.search_long_term_memory, args: { text: "{inputs.query}" } }
          code: { tool: github.search_code, args: { query: "{inputs.query}" } }

    # Python custom tools
    custom_tools:
      - module: hooks.expert.contextual_search
      - module: hooks.expert.smart_issue_creator
```

## CLI Tools

### Schema Inspection

Inspect upstream tool schemas to understand compatibility for composition:

```bash
# List all configured upstream servers
$ mcp-proxy servers
redis-memory-server  (command: uv tool run ...)
github               (url: https://api.githubcopilot.com/mcp/)

# List all tools from all servers
$ mcp-proxy tools
redis-memory-server:
  - search_long_term_memory
  - create_long_term_memories
  - memory_prompt
  - get_working_memory
  - set_working_memory
github:
  - search_code
  - search_issues
  - search_pull_requests
  ... (40 tools)

# Show detailed schema for a specific tool
$ mcp-proxy schema redis-memory-server.search_long_term_memory
Tool: search_long_term_memory
Description: Search for memories related to a query...

Parameters:
  text (string, required): The query for vector search
  session_id (object, optional): Filter by session ID
  namespace (object, optional): Filter by namespace
  topics (object, optional): Filter by topics
  limit (integer, default=10): Maximum number of results
  offset (integer, default=0): Offset for pagination

Returns: MemoryRecordResults containing matched memories

# Show schemas for all tools from one server
$ mcp-proxy schema --server github

# Export all schemas to JSON (for programmatic use)
$ mcp-proxy schema --json > schemas.json

# Validate config and test upstream connections
$ mcp-proxy validate
✓ redis-memory-server: connected (18 tools)
✓ github: connected (40 tools)
✓ tool_views.redis-expert: valid (3 tools exposed)
✓ tool_views.unified-search: valid (1 composite tool)
✗ tool_views.broken: ERROR - references unknown tool 'foo.bar'
```

### Other CLI Commands

```bash
# Start the proxy server
$ mcp-proxy serve --config config.yaml --transport stdio
$ mcp-proxy serve --config config.yaml --transport http --port 8080

# Test a specific tool call
$ mcp-proxy call redis-memory-server.search_long_term_memory --text "hello"

# Show effective config after env var substitution
$ mcp-proxy config --resolved

# Generate example hooks file
$ mcp-proxy init hooks
```

## Key FastMCP 2 Features Used

1. **`FastMCP.as_proxy()`** - Create proxy connections to upstream servers
2. **`ProxyClient`** - Session-isolated client for upstream connections
3. **`Tool.from_tool()`** - Transform tools with modified descriptions/behavior
4. **`transform_fn`** - Custom logic wrapping tool execution
5. **MCPConfig format** - Configuration-based server connections
6. **Component prefixing** - Automatic namespacing when mounting servers

## Summary

This design provides:

| Requirement | Solution |
|-------------|----------|
| Tool views as virtual servers | `ToolView` class aggregates tools from multiple upstreams |
| Tool definition override with `{original}` | `_transform_tool()` method with placeholder substitution |
| Config-driven | YAML config with Pydantic validation |
| Pre/post call hooks | `HookResult` pattern with abort capability |
| Direct vs search exposure modes | `exposure_mode` config with `ToolSearcher` meta-tool |
| Authentication space | Hook system provides natural extension points |
| Parallel fan-out | `parallel:` config runs multiple tools simultaneously |
| Custom tools | Python `@custom_tool` decorator with full `ProxyContext` access |
| Schema inspection | `mcp-proxy schema` CLI for debugging and composition planning |

The implementation leverages FastMCP 2's native proxying, tool transformation, and composition features to minimize custom code while providing the flexibility needed for tool view management.

### Composition Decision Tree

```
Need to combine multiple tools?
│
├─ Run independently, collect all results?
│  └─ Use: parallel (fan-out)
│
├─ Need sequential calls or transformation between steps?
│  └─ Use: custom_tool (Python)
│
└─ Just filter, rename, or modify descriptions?
   └─ Use: tools with ToolConfig (name, description, enabled)
```

