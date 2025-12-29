# ADR-003: Parameter Binding and Modular Architecture

## Status

Accepted

## Context

After the initial implementation (ADR-002), several enhancements were needed to support real-world usage patterns and improve code maintainability. These changes were implemented between December 24-29, 2025.

## Key Decisions

### 1. Parameter Binding

**Problem**: Tools often expose parameters that should be hidden from users (e.g., API keys, fixed paths) or use technical names that don't match the domain language.

**Solution**: Added `ParameterConfig` model allowing per-parameter customization:

```yaml
mcp_servers:
  github:
    url: https://api.github.com/mcp
    tools:
      search_code:
        parameters:
          repo:
            hidden: true
            default: "my-org/my-repo"  # Always search this repo
          q:
            rename: query  # More intuitive name
            description: "Search query string"
```

**Implementation**:
- `ParameterConfig` model with `hidden`, `default`, `rename`, `description` fields
- `transform_schema()` modifies JSON Schema to reflect parameter changes
- `transform_args()` injects defaults and remaps names at call time
- Hidden parameters are removed from schema but injected with defaults during execution

**Rationale**: Enables tool customization without modifying upstream servers. Essential for creating domain-specific tool interfaces.

### 2. Tool Aliasing

**Problem**: Need to expose the same tool under multiple names with different configurations (e.g., `search_my_repo` and `search_all_repos` from same base tool).

**Solution**: Added `AliasConfig` allowing multiple aliases per tool:

```yaml
tools:
  search_code:
    aliases:
      - name: search_my_repo
        description: "Search in my repository"
      - name: search_all_repos
        description: "Search across all repositories"
```

**Rationale**: Enables creating specialized tool variants without duplicating configuration.

### 3. Modular Package Architecture

**Problem**: `cli.py` (1,266 lines) and `proxy.py` (1,181 lines) had become difficult to maintain. The `get_view_tools()` function alone was 302 lines with cyclomatic complexity of 51.

**Solution**: Refactored into focused packages:

```
mcp_proxy/
├── cli/                    # Was: cli.py (1,266 lines)
│   ├── __init__.py         # Entry point, exports main()
│   ├── utils.py            # Shared utilities (70 lines)
│   ├── commands.py         # serve, show, validate, call (381 lines)
│   ├── server.py           # server subcommands (404 lines)
│   └── view.py             # view subcommands (429 lines)
├── proxy/                  # Was: proxy.py (1,181 lines)
│   ├── __init__.py         # Public API exports
│   ├── client.py           # ClientManager class (154 lines)
│   ├── schema.py           # Schema transformation (147 lines)
│   ├── tool_info.py        # ToolInfo data class (31 lines)
│   ├── tools.py            # get_view_tools logic (400 lines)
│   └── proxy.py            # MCPProxy class (612 lines)
```

**Backward Compatibility**: `mcp_proxy.proxy` re-exports all public symbols including `_transform_schema` and `_transform_args` aliases for tests.

**Metrics Improvement**:
- Maintainability Index: 0.79 → 0.82
- Halstead Volume: 0.88 → 0.94
- Cognitive Complexity: 0.84 → 0.90

### 4. Test Suite Modularization

**Problem**: Test files mirrored the monolithic structure with `test_proxy.py` at 2,481 lines.

**Solution**: Split into test packages matching source structure:

```
tests/
├── test_proxy/             # Was: test_proxy.py (2,481 lines)
│   ├── test_initialization.py
│   ├── test_connections.py
│   ├── test_registration.py
│   ├── test_execution.py
│   ├── test_schema.py
│   ├── test_parameters.py
│   └── ... (15 modules)
├── test_views/
│   ├── test_initialization.py
│   ├── test_call_tool.py
│   └── ... (6 modules)
└── test_integration_http/
    └── ... (4 modules)
```

### 5. CI/CD Pipeline

**Implementation**: GitHub Actions workflow with:
- Lint job: `ruff check` + `ruff format --check`
- Test job: pytest across Python 3.11, 3.12, 3.13
- Coverage requirement: 100% (enforced via `--cov-fail-under=100`)

**Local Development**: Makefile for common tasks:
```bash
make check   # lint + format-check
make test    # pytest with coverage
make format  # auto-format
make all     # check + test
```

### 6. Working Directory Support for Stdio Servers

**Addition**: `cwd` field on `UpstreamServerConfig` for stdio-based servers:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["@anthropic/mcp-fs"]
    cwd: /data/projects  # Server runs in this directory
```

Supports environment variable expansion: `cwd: ${PROJECT_ROOT}`.

## Consequences

- Parameter binding enables tool customization without upstream changes
- Aliasing supports multiple specialized interfaces from single tools
- Modular architecture improves maintainability and enables parallel development
- 100% coverage requirement ensures comprehensive testing
- CI automation catches regressions before merge

