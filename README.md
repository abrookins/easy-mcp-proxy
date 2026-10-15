# Easy MCP Proxy

An MCP proxy server that aggregates tools from multiple upstream MCP servers and exposes them through **tool views** — filtered, transformed, and composed subsets of tools.

> **Status**: Experimental

📖 **[Full Documentation](docs/index.md)** | 🚀 **[Tutorial](docs/tutorial.md)** | 📚 **[Reference](docs/reference.md)**

## Quick Start

### 1. Install and prepare a configuration

From the repository checkout:

```bash
uv sync --frozen
```

Create `config.yaml` with an existing directory that the service may access:

```yaml
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

YAML is an import format and a local inspection input. The running service reads
an encrypted, user-owned store. Existing deployments should follow the
[migration guide](docs/user-owned-configuration.md#migrate-an-existing-installation)
to preserve OAuth state before starting this version.

### 2. Provision the owner and import

For a new local installation, use the owner's verified OAuth issuer and subject.
Replace the placeholders before running these commands:

```bash
export MCP_PROXY_STATE_DIR="$HOME/.local/state/easy-mcp-proxy"
export MCP_PROXY_OWNER_ISSUER='https://YOUR-ISSUER/'
export MCP_PROXY_OWNER_SUBJECT='VERIFIED-SUBJECT'
proxy_user_id=$(uv run mcp-proxy users provision \
  --issuer "$MCP_PROXY_OWNER_ISSUER" --subject "$MCP_PROXY_OWNER_SUBJECT" --operator)
uv run mcp-proxy users grant "$proxy_user_id" \
  --client mcp-proxy-local --admin --view default
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml --apply
```

The first import validates without activating. Import requires the runtime to be
stopped. `--operator` permits this owner to configure host processes and upstream
destinations; grant it only to a trusted host operator.

### 3. Connect a client

For local stdio, run `uv run mcp-proxy serve` with the three environment variables
above. A desktop client can launch it using the
[stdio configuration example](docs/tutorial.md#option-a-stdio-for-a-local-client).
Only one runtime can use a state directory at a time.

For a remote service, complete the [OAuth and grant setup](docs/user-owned-configuration.md#bootstrap-and-grants), then start:

```bash
uv run mcp-proxy serve --transport http --port 8000
```

Connect an OAuth-capable MCP client to `https://YOUR-PROXY/mcp` or a granted
`/view/NAME/mcp` endpoint. Open `https://YOUR-PROXY/config` for browser administration.
The [acceptance record](docs/specs/remote-configuration-acceptance.md) distinguishes
local verification from pending Claude/ChatGPT and physical-device checks.

### 4. Change configuration while running

Use the browser editor or `mcp-proxy manage` to preview, probe, and apply changes.
Unchanged upstream connections are reused; replaced connections drain existing
calls for up to 10 seconds. Clients may need to refresh their tool list.
Editing the original YAML has no effect until an offline import; passing
`--config` to `serve` is rejected.

## Example Use Cases

The YAML below describes configuration fields. Import it for an explicit owner,
or edit the equivalent JSON in the browser and preview/apply it.

### Reduce Tool Count with Search Mode

Too many tools overwhelming your LLM? Expose hundreds of tools through three meta-tools:

```yaml
tool_views:
  everything:
    exposure_mode: search
    include_all: true
```

This creates `everything_search_tools` (find tools), `everything_describe_tool`
(inspect one exact schema), and `everything_call_tool` (validate and call by
name). The LLM searches, describes, then calls—no need to list every tool.

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

### Keep Large Outputs Bounded by Default

Large tool outputs (file contents, search results, minified JSON, JSONL, logs) can overwhelm LLM context. Easy MCP Proxy measures every proxied tool result after the upstream server responds. Oversized results are cached and the model receives a bounded preview with navigation metadata.

Safe output handling is enabled by default. Use `output_cache` to tune limits or explicitly disable it for trusted local debugging:

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600
  max_inline_tokens: 3000
  max_line_chars: 1200
  retrieval_default_line_count: 100
  retrieval_max_line_count: 500
  retrieval_max_chars: 12000
```

The LLM gets a preview plus a retrieval token. It can request line windows with
`preview_cached_output`, character windows with `range_cached_output`, or JSON
slices with `query_cached_output`. `retrieve_cached_output` and `/view/{view}/cache/{token}`
return bounded content by default; append `download=1` or `full=1` to the signed
HTTP URL for explicit full-content processing outside the model context.
HTTP retrieval also requires OAuth or a browser session for the same owner and
view. The service manages cache keys and URLs.
This enables **Recursive Language Model (RLM)** patterns where agents pass file
references instead of file contents, dramatically reducing context usage while
maintaining full access to the data.

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
- **[Tool discovery](docs/tool-discovery.md)** — Schemas, safe calls, local/live inspection, and rollout

## Development

```bash
uv sync --frozen
make check  # Lint
make test   # Run tests (requires 100% coverage)
```

## License

AGPL-3.0 — See [LICENSE](LICENSE)

## Administration and migration

`mcp-proxy serve` now uses explicitly provisioned, OAuth-owned configuration from
`MCP_PROXY_STATE_DIR`. Import existing YAML and OAuth state before upgrading;
there is no global configuration fallback. Live preview/apply, encrypted secret
references, client grants, remote CLI, responsive browser administration, and
portable MCP Apps administration are described in the
[user-owned configuration guide](docs/user-owned-configuration.md).
See the [acceptance record](docs/specs/remote-configuration-acceptance.md) for
verified behavior and outstanding real-client release checks.
