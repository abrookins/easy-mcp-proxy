# Easy MCP Proxy Documentation

Easy MCP Proxy is an aggregation layer for [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers. It connects to multiple upstream MCP servers and exposes their tools through a single, configurable interface.

## Why Use a Proxy?

MCP servers provide tools to AI assistants. As you add more servers—filesystem access, GitHub, memory systems, APIs—you encounter challenges:

- **Tool overload**: Too many tools confuse the LLM about which to use
- **Inconsistent interfaces**: Each server has its own naming conventions
- **No composition**: You can't combine tools from different servers
- **Management complexity**: Each client needs separate configuration for each server

Easy MCP Proxy solves these by sitting between your MCP clients and upstream servers:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Claude Desktop │     │  Easy MCP Proxy │     │  MCP Servers    │
│  or other       │────▶│                 │────▶│  - filesystem   │
│  MCP client     │     │  Tool Views     │     │  - github       │
│                 │◀────│  Composition    │◀────│  - memory       │
│                 │     │  Transformation │     │  - zapier       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Core Concepts

### Upstream Servers

MCP servers that provide tools. Can be:
- **Stdio servers**: Local processes (e.g., `npx @modelcontextprotocol/server-filesystem`)
- **HTTP servers**: Remote endpoints (e.g., Zapier MCP)

### Tool Views

Named configurations that define which tools to expose and how. Each view can:
- Include specific tools from specific servers
- Rename tools and parameters
- Override descriptions
- Use different exposure modes

### Exposure Modes

How tools are presented to the client:
- **direct**: Each tool exposed individually (default)
- **search**: Two meta-tools (`search_tools` + `call_tool`) for the entire view
- **search_per_server**: Meta-tools per upstream server

### Parameter Binding

Transform tool interfaces by:
- Hiding parameters (set fixed values)
- Renaming parameters (clearer naming)
- Setting defaults (make required params optional)
- Overriding descriptions

### Composite Tools

New tools that orchestrate multiple upstream tools:
- **Concurrent composition**: Fan-out to multiple tools via `asyncio.gather`
- **Custom tools**: Python functions with full upstream access

### Output Caching

Large tool outputs can consume valuable LLM context window space. Output caching:
- Stores outputs exceeding a size threshold
- Returns a preview plus a retrieval token
- Provides both tool-based and HTTP retrieval methods
- Uses HMAC-signed expiring URLs for security

## Documentation Structure

| Document | Description |
|----------|-------------|
| **[Tutorial](tutorial.md)** | Step-by-step guide from installation to advanced features |
| **[Use Cases](use-cases.md)** | Problem-driven exploration—find features by what you want to accomplish |
| **[Reference](reference.md)** | Complete feature documentation organized by capability |

## Quick Links

- **Getting started?** → [Tutorial](tutorial.md)
- **Have a specific problem?** → [Use Cases](use-cases.md)
- **Need detailed syntax?** → [Reference](reference.md)
- **Architectural decisions?** → [Decision Records](decisions/)

## Installation

```bash
# Install from source
uv pip install -e .

# With dev dependencies
uv pip install -e ".[dev]"
```

## Minimal Example

```yaml
# config.yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/docs]

tool_views:
  default:
    tools:
      filesystem:
        read_file: {}
        list_directory: {}
```

```bash
mcp-proxy serve --config config.yaml
```

This exposes `read_file` and `list_directory` from the filesystem server. Other tools from that server are filtered out.

## Next Steps

1. **[Follow the Tutorial](tutorial.md)** — Complete walkthrough from basics to advanced features
2. **[Explore Use Cases](use-cases.md)** — Find solutions to specific problems
3. **[Check the Reference](reference.md)** — Deep dive into any feature

