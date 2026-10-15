# Easy MCP Proxy

Easy MCP Proxy sits between your MCP clients (Claude Desktop, coding agents,
ChatGPT connectors) and the MCP servers you use. It combines the tools from
several upstream servers and exposes them through **views**: named endpoints
that each show a chosen, optionally renamed and reshaped, set of tools.

Status: experimental.

## Features

- **Aggregate** stdio and HTTP MCP servers behind one endpoint
- **Filter** which tools each view exposes
- **Rename** tools and parameters, rewrite descriptions, and hide parameters
  behind fixed defaults
- **Search mode** to expose hundreds of tools through a few search/describe/call tools
- **Composite tools** that call several upstream tools concurrently
- **Bounded outputs**: large results are cached and returned as a preview the
  model can page through
- **Hooks** and custom Python tools
- **Live administration** from a browser, CLI, or MCP, with preview, apply,
  history, and rollback. No restart needed.
- **Per-user configuration** with OAuth sign-in and API keys

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/abrookins/easy-mcp-proxy.git
cd easy-mcp-proxy
uv sync --frozen
```

## Quick start

### 1. Describe your servers and views

Create `config.yaml`:

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

The running proxy doesn't read this file directly. You import it once into the
proxy's encrypted state directory, and make later changes through the
administration UI or CLI.

### 2. Create your account and import the config

Each configuration belongs to a user, identified by an OAuth issuer and
subject. If you'll serve over HTTP, these must match the identity your OAuth
provider issues for you. For local stdio use, any stable values work.

```bash
export MCP_PROXY_STATE_DIR="$HOME/.local/state/easy-mcp-proxy"
export MCP_PROXY_OWNER_ISSUER='https://YOUR-ISSUER/'
export MCP_PROXY_OWNER_SUBJECT='YOUR-SUBJECT'

user_id=$(uv run mcp-proxy users provision \
  --issuer "$MCP_PROXY_OWNER_ISSUER" --subject "$MCP_PROXY_OWNER_SUBJECT" --operator)
uv run mcp-proxy users grant "$user_id" --client mcp-proxy-local --admin --view default

# Check the import, then apply it
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml
uv run mcp-proxy users import --issuer "$MCP_PROXY_OWNER_ISSUER" \
  --subject "$MCP_PROXY_OWNER_SUBJECT" --config config.yaml --apply
```

`--operator` lets this user configure commands, URLs, hooks, and custom code
that run on the host. Give it only to someone you'd trust with a shell on the
machine.

### 3. Run it

**Locally over stdio.** With the three variables above set, run:

```bash
uv run mcp-proxy serve
```

See the [tutorial](docs/tutorial.md#option-a-stdio-for-a-local-client) for a
Claude Desktop configuration.

**As a remote HTTP service.** Configure your OAuth provider and grant your
browser and clients access, as described in
[Bootstrap and grants](docs/user-owned-configuration.md#bootstrap-and-grants).
Then run:

```bash
uv run mcp-proxy serve --transport http --port 8000
```

MCP clients connect to `https://YOUR-PROXY/mcp` (the `default` view) or
`https://YOUR-PROXY/view/NAME/mcp`.

### 4. Manage it

Open `https://YOUR-PROXY/config` in a browser to edit servers, views, and
output settings. Every change is previewed first and applied live; clients may
need to refresh their tool list. The same operations are available through
`mcp-proxy manage` and an admin MCP endpoint.

The browser's **API keys** page lets you create keys so agents can connect as
you without browser sign-in. Each key is limited to the views you choose.

To make people admins by email, set `MCP_PROXY_ADMIN_EMAILS`. This works only
when your OAuth provider includes a verified email in its tokens; see the
[admin email list](docs/user-owned-configuration.md#admin-email-list).

## Examples

You can import these as YAML, or paste the equivalent JSON into the browser's
JSON editor.

### Expose many tools through search

```yaml
tool_views:
  everything:
    exposure_mode: search
    include_all: true
```

Clients see three tools: `everything_search_tools`, `everything_describe_tool`,
and `everything_call_tool`. The model searches for a tool, reads its schema,
then calls it, so you don't need to list every tool up front.

### Build a domain-specific interface

Present generic filesystem tools as a skills library:

```yaml
mcp_servers:
  skills:
    command: npx
    args: [-y, "@modelcontextprotocol/server-filesystem", /home/user/skills]
    tools:
      read_file:
        name: get_skill
        parameters:
          path:
            rename: skill_name
            description: "Skill file path (e.g., 'python/debugging.md')"
      directory_tree:
        name: browse_skills
        parameters:
          path:
            hidden: true   # not shown to the model
            default: "."   # always browse from the root
```

### Search several sources at once

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

### Keep large outputs out of the context window

Output limits are on by default. When a result is too large, the proxy caches
it and returns a preview plus a token. The model can then read line ranges
(`preview_cached_output`), character ranges (`range_cached_output`), or JSON
slices (`query_cached_output`) as needed. Tune the limits with `output_cache`:

```yaml
output_cache:
  enabled: true
  max_inline_tokens: 3000
  max_line_chars: 1200
  ttl_seconds: 3600
```

## Documentation

- [Introduction](docs/index.md): concepts and overview
- [Tutorial](docs/tutorial.md): step-by-step setup
- [Use cases](docs/use-cases.md): examples organized by problem
- [Reference](docs/reference.md): configuration fields and CLI
- [User-owned configuration](docs/user-owned-configuration.md): OAuth, grants,
  API keys, live changes, backup and restore, and upgrading from YAML-based versions
- [Tool discovery](docs/tool-discovery.md): inspecting schemas and calling tools safely

## Development

```bash
uv sync --frozen
make check   # lint and format check
make test    # tests, with 100% coverage required
```

## License

AGPL-3.0. See [LICENSE](LICENSE).
