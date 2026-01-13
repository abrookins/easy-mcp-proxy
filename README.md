# Easy MCP Proxy

An MCP proxy server that aggregates tools from multiple upstream MCP servers and exposes them through **tool views** — filtered, transformed, and composed subsets of tools.

> **Status**: Experimental

📖 **[Full Documentation](docs/index.md)** | 🚀 **[Tutorial](docs/tutorial.md)** | 📚 **[Reference](docs/reference.md)**

## Quick Start

### 1. Install

```bash
uv pip install -e .
```

### 2. Create a config file

```yaml
# config.yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/documents]

tool_views:
  default:
    tools:
      filesystem:
        read_file: {}
        list_directory: {}
```

### 3. Run the proxy

```bash
# For Claude Desktop (stdio)
mcp-proxy serve --config config.yaml

# For HTTP clients
mcp-proxy serve --config config.yaml --transport http --port 8000
```

### 4. Use with Claude Desktop

Add to `claude_desktop_config.json`:

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

## Example Use Cases

### Reduce Tool Count with Search Mode

Too many tools overwhelming your LLM? Expose hundreds of tools through just two meta-tools:

```yaml
tool_views:
  everything:
    exposure_mode: search
    include_all: true
```

This creates `everything_search_tools` (find tools by description) and `everything_call_tool` (call by name). The LLM searches first, then calls—no need to list every tool.

### Create Domain-Specific Interfaces

Wrap generic filesystem tools into a purpose-built "skills library" interface:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/skills]
    tools:
      read_file:
        name: get_skill           # Rename for clarity
        parameters:
          path:
            rename: skill_name    # Domain-specific parameter name
            description: "Skill file path (e.g., 'python/debugging.md')"
      directory_tree:
        name: browse_skills
        parameters:
          path:
            hidden: true          # Hide implementation detail
            default: "."          # Always start at root
```

### Search Multiple Sources Concurrently

Create a unified search that queries all your knowledge sources at once:

```yaml
tool_views:
  unified:
    composite_tools:
      search_everything:
        description: "Search code, docs, and memory simultaneously"
        inputs:
          query: { type: string, required: true }
        parallel:
          code:
            tool: github.search_code
            args: { query: "{inputs.query}" }
          docs:
            tool: confluence.search
            args: { query: "{inputs.query}" }
          memory:
            tool: memory.search
            args: { text: "{inputs.query}" }
```

### Reduce Context Usage with Output Caching

Large tool outputs (file contents, search results) consume valuable LLM context. Cache them and return a preview:

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600        # URLs valid for 1 hour
  preview_chars: 500       # Show first 500 chars inline
  min_size: 10000          # Only cache outputs > 10KB

cache_secret: "${CACHE_SECRET}"
cache_base_url: "https://your-proxy.example.com"
```

The LLM gets a preview plus a retrieval token—it can load the full content only when needed.

## What Can It Do?

- **Aggregate** multiple MCP servers (stdio or HTTP) into one endpoint
- **Filter** which tools are exposed from each server
- **Rename** tools and parameters for clearer interfaces
- **Bind** parameter defaults or hide implementation details
- **Compose** concurrent tools that fan out to multiple upstreams
- **Cache** large outputs to reduce context window usage
- **Transform** with pre/post hooks for logging, validation, or modification
- **Serve** via stdio (Claude Desktop) or HTTP with multi-view routing

See the **[Use Cases Guide](docs/use-cases.md)** for detailed examples of each capability.

## Documentation

- **[Introduction](docs/index.md)** — Overview and concepts
- **[Tutorial](docs/tutorial.md)** — Step-by-step getting started guide
- **[Use Cases](docs/use-cases.md)** — Problem-driven feature exploration
- **[Reference](docs/reference.md)** — Complete feature and CLI documentation

## Development

```bash
uv pip install -e ".[dev]"
make check  # Lint
make test   # Run tests (requires 100% coverage)
```

## License

AGPL-3.0 — See [LICENSE](LICENSE)
