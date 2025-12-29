# Agent Guide for easy-mcp-proxy

Essential information for AI agents working on this codebase.

## Quick Commands

```bash
make check      # Run linting + format check (run before committing)
make test       # Run all tests (510 tests, requires 100% coverage)
make format     # Auto-format code with ruff
make all        # Run check + test (full CI simulation)
```

## Project Overview

An MCP proxy server that aggregates tools from multiple upstream MCP servers and exposes them through **tool views** — filtered, transformed, and composed subsets of tools.

**Key dependencies**: `fastmcp>=2.0.0`, `pydantic>=2.0.0`, `click>=8.0.0`

## Source Code Structure

```
mcp_proxy/
├── cli/                 # CLI commands (Click-based)
│   ├── commands.py      # Main commands (serve, show, validate)
│   ├── server.py        # Server subcommands (add, remove, set-*)
│   ├── view.py          # View subcommands (add, remove, set-*)
│   └── utils.py         # CLI utilities
├── proxy/               # Core proxy logic
│   ├── proxy.py         # MCPProxy class - main entry point
│   ├── client.py        # Upstream client management
│   ├── tools.py         # Tool registration and get_view_tools()
│   ├── schema.py        # JSON schema transformations
│   └── tool_info.py     # ToolInfo data class
├── models.py            # Pydantic models (ProxyConfig, ToolConfig, etc.)
├── views.py             # ToolView class for view execution
├── hooks.py             # Pre/post hook system
├── custom_tools.py      # Custom Python tool loading
├── parallel.py          # Parallel tool composition
├── config.py            # Configuration loading
└── tools/               # Built-in custom tools
```

## Test Structure

```
tests/
├── test_cli.py          # CLI tests (largest file)
├── test_proxy_main.py   # Main proxy tests
├── test_proxy/          # Proxy unit tests by feature
├── test_views/          # ToolView tests
├── test_integration_http/  # HTTP transport integration tests
└── conftest.py          # Shared fixtures
```

## Code Quality Requirements

1. **100% test coverage** - Required by CI (`--cov-fail-under=100`)
2. **Ruff linting** - Rules: E, F, I, W (errors, pyflakes, isort, warnings)
3. **Line length**: 88 characters max
4. **Python version**: 3.11+

## Key Patterns

### Configuration Model
```python
from mcp_proxy.models import ProxyConfig, UpstreamServerConfig, ToolConfig
config = ProxyConfig(
    mcp_servers={"server": UpstreamServerConfig(command="echo")},
    tool_views={}
)
```

### Creating MCPProxy
```python
from mcp_proxy.proxy import MCPProxy
proxy = MCPProxy(config)
tools = proxy.get_view_tools("view_name", upstream_tools)
```

### Testing Pattern
- Use `pytest` with `pytest-asyncio`
- Tests use `@pytest.mark.asyncio` decorator (auto-applied)
- Mock upstream clients with `unittest.mock`
- CLI tests use Click's `CliRunner`

## Common Pitfalls

1. **Long lines in docstrings** - Break multi-line docstrings properly
2. **Unused imports** - Ruff will catch these; run `make check` before committing
3. **Async tests** - Always use `async def` for tests that call async code
4. **Coverage gaps** - Every new code path needs a test

## Architecture Decisions

See `docs/decisions/` for architectural context:
- `001-initial-design.md` - Original design rationale
- `002-implementation-changes.md` - Evolution from original design

## Entry Points

- **CLI**: `mcp_proxy.cli:main` (registered as `mcp-proxy` command)
- **Proxy**: `mcp_proxy.proxy:MCPProxy`
- **Views**: `mcp_proxy.views:ToolView`

## When Adding Features

1. Update models in `models.py` if config changes needed
2. Add tests first (TDD encouraged)
3. Run `make check` before committing
4. Ensure 100% coverage with `make test`
5. Update CLI if user-facing changes

