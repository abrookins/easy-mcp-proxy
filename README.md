# MCP Tool View Proxy

MCP proxy server that provides tool views - filtered, transformed, and composed subsets of tools from upstream MCP servers.

See [DESIGN.md](DESIGN.md) for architecture details.

## Installation

```bash
uv pip install -e ".[dev]"
```

## Usage

```bash
mcp-proxy serve --config config.yaml
```

