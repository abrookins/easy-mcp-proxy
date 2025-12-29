# Easy MCP Proxy Examples

This document contains practical examples of using Easy MCP Proxy to create
powerful, customized tool configurations.

## Table of Contents

- [Portable Skills Library](#portable-skills-library)
- [GitHub Read-Only Tools](#github-read-only-tools)
- [Tool Views for Different Contexts](#tool-views-for-different-contexts)
- [Custom Python Tools with MFCQI](#custom-python-tools-with-mfcqi)

---

## Portable Skills Library

This example creates a **portable skills storage system** that syncs with your
Obsidian notes vault and exposes domain-specific "Skills" tools by wrapping a
generic filesystem MCP server.

### The Problem

The `@modelcontextprotocol/server-filesystem` server exposes generic file
operations like `read_file`, `write_file`, and `list_directory`. These work
fine, but:

1. The tool names don't communicate their purpose to the AI
2. Parameters like `path` require knowledge of the directory structure
3. There's no context about what the files contain or how to use them

### The Solution

Wrap the filesystem server with MCP Proxy to create a purpose-built "Skills
Library" interface that:

- Renames tools to reflect their domain (e.g., `read_file` → `read_skill_file`)
- Adds rich descriptions explaining when and how to use each tool
- Hides or defaults parameters to simplify the interface
- Points to your Obsidian vault so skills sync across devices

### Configuration

```yaml
mcp_servers:
  # Portable Skills Library - wraps filesystem server
  # Points to Obsidian vault for cross-device sync
  skills-library:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - /Users/you/Documents/Obsidian/Skills  # Your Obsidian vault path
    cwd: /Users/you/Documents/Obsidian/Skills
    tools:
      # Reading skills
      read_text_file:
        name: read_skill_file
        description: |
          Read a skill file from the skills library. Use this to retrieve
          the full contents of a specific skill document (markdown, yaml,
          json, etc.) by its path within the skills folder.
          {original}
        parameters:
          path:
            description: "Path to skill file (e.g., 'deployment/kubernetes.md')"

      read_multiple_files:
        name: read_multiple_skill_files
        description: |
          Read multiple skill files simultaneously. Use this to efficiently
          retrieve the contents of several skill documents at once.
        parameters:
          paths:
            description: "Array of paths to skill files"

      # Browsing skills
      list_directory:
        name: list_skill_categories
        description: |
          List skill categories or files in a directory. Use this to browse
          the skills library and discover available skill documents organized
          by category or topic.
          {original}
        parameters:
          path:
            rename: category
            default: "."
            description: "Category folder to list (e.g., 'deployment')"

      search_files:
        name: search_skill_files
        description: |
          Search for skill files by name pattern. Use this to find skill
          documents matching keywords like "deploy", "debug", "setup",
          "migration", etc. Returns file paths that match the pattern.
        parameters:
          path:
            hidden: true
            default: "."
          pattern:
            description: "Glob pattern (e.g., '**/*.md', '**/deploy*')"
          excludePatterns:
            default: []
            description: "Patterns to exclude from results"

      directory_tree:
        name: get_skills_structure
        description: |
          Get the full directory tree of the skills library. Use this to
          understand the overall organization of skills and see all
          available categories and documents at a glance.
          {original}
        parameters:
          path:
            hidden: true
            default: "."
          excludePatterns:
            default: []

      # Writing skills
      write_file:
        name: save_skill_file
        description: |
          Save a new skill file to the skills library. Use this to create
          new skill documents with step-by-step procedures, tips, and
          examples. Use appropriate file extensions (.md for markdown,
          .yaml for structured data).
          {original}
        parameters:
          path:
            rename: skill_path
            description: "Path for new skill file (e.g., 'deployment/new-guide.md')"
          content:
            description: "The content of the skill file (markdown recommended)"

      edit_file:
        name: update_skill_file
        description: |
          Edit an existing skill file. Use this to update procedures,
          add new steps, fix errors, or enhance documentation in a
          skill document.
          {original}
        parameters:
          path:
            description: "Path to the skill file to edit"

      # Organization
      create_directory:
        name: create_skill_category
        description: |
          Create a new category (subdirectory) in the skills library.
          Use this to organize skills into logical groups.
        parameters:
          path:
            description: "Path for new category (e.g., 'deployment/kubernetes')"

      move_file:
        name: move_skill_file
        description: |
          Move or rename a skill file or category. Use this to reorganize
          the skills library structure.
        parameters:
          source:
            description: "Current path of the skill file or category"
          destination:
            description: "New path for the skill file or category"

      get_file_info:
        name: get_skill_file_info
        description: |
          Get detailed metadata about a skill file. Returns size, creation
          time, modified time, and permissions.
        parameters:
          path:
            description: "Path to the skill file or category"
```

### How It Works

1. **Obsidian Sync**: By pointing to your Obsidian vault, skills automatically
   sync across all your devices via Obsidian Sync, iCloud, or your preferred
   sync method.

2. **AI-Friendly Names**: Instead of asking the AI to "read a file," it now
   understands it's reading from a "skills library" with domain-specific tools.

3. **Simplified Parameters**: The `path` parameter in `directory_tree` is hidden
   and defaults to `.`, so the AI can call `get_skills_structure` with no
   arguments to see the full library.

4. **Rich Context**: Descriptions explain *when* to use each tool, not just
   *what* it does. This helps the AI make better decisions about which tool
   to call.

### Example Skills Structure

```
Skills/
├── deployment/
│   ├── kubernetes.md
│   ├── docker-compose.md
│   └── ci-cd-pipelines.md
├── debugging/
│   ├── memory-leaks.md
│   ├── performance-profiling.md
│   └── log-analysis.md
├── coding-patterns/
│   ├── error-handling.md
│   ├── async-patterns.md
│   └── testing-strategies.md
└── tools/
    ├── git-workflows.md
    ├── vim-shortcuts.md
    └── shell-scripts.md
```

---

## GitHub Read-Only Tools

This example configures the GitHub MCP server with a **reduced, read-only tool
set** — perfect for AI assistants that need to search and read code but
shouldn't create issues, PRs, or modify repositories.

### The Problem

The full GitHub MCP server exposes many tools including destructive operations
like creating issues, commenting, and modifying repository settings. For many
use cases, you only want search and read capabilities.

### The Solution

Use Easy MCP Proxy's tool filtering to expose only the safe, read-only tools:

### Configuration

```yaml
mcp_servers:
  github:
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_PERSONAL_ACCESS_TOKEN}"
    # Expose ONLY search and read tools - no create/update/delete
    tools:
      # Search tools
      search_code: {}
      search_issues: {}

      # Repository content
      get_file_contents: {}
      list_commits: {}

      # Issues (read-only)
      list_issues: {}
      get_issue: {}

      # Pull requests (read-only)
      list_pull_requests: {}
      get_pull_request: {}
      get_pull_request_files: {}
      get_pull_request_status: {}
```

### What's Excluded

By explicitly listing only these tools, the following are **not exposed**:

- `create_issue` - Can't create new issues
- `update_issue` - Can't modify existing issues
- `add_issue_comment` - Can't add comments
- `create_pull_request` - Can't create PRs
- `merge_pull_request` - Can't merge PRs
- `create_branch` - Can't create branches
- `push_files` - Can't push code
- `fork_repository` - Can't fork repos
- And many more write operations...

### Use Cases

- **Code review assistants** that analyze PRs but don't comment
- **Documentation generators** that read code but don't commit
- **Security scanners** that search for patterns but don't file issues
- **Learning tools** that explore codebases safely

---

## Tool Views for Different Contexts

Tool views let you create **named configurations** that expose different subsets
of tools for different use cases. This is useful when you want to:

- Give different AI assistants access to different capabilities
- Create "safe" vs "full access" modes
- Organize tools by workflow or domain
- Serve different tool sets via different HTTP endpoints

### The Problem

You have multiple upstream MCP servers with many tools, but different contexts
need different tool combinations:

- A **support assistant** needs memory + ticket tools, but not code tools
- A **code reviewer** needs GitHub read tools + code quality, but not write tools
- A **full developer assistant** needs everything

### The Solution

Define multiple tool views in your configuration, each exposing a curated set
of tools:

### Configuration

```yaml
mcp_servers:
  # Define your upstream servers...
  github:
    command: npx
    args: [-y, "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_PERSONAL_ACCESS_TOKEN}"

  memory-server:
    command: uv
    args: [tool, run, --from, agent-memory-server, agent-memory, mcp]
    env:
      REDIS_URL: redis://localhost:6379

  zendesk:
    command: uv
    args: [tool, run, --from, zendesk-mcp-server, zendesk]


# Tool views - named configurations exposing different tool subsets
tool_views:
  # Full access for developer assistants
  developer:
    description: "Full developer toolkit with all capabilities"
    include_all: true
    custom_tools:
      - module: tools.mfcqi.analyze_code_quality

  # Read-only for code exploration and learning
  explorer:
    description: "Safe read-only tools for code exploration"
    tools:
      github:
        search_code: {}
        search_issues: {}
        get_file_contents: {}
        list_commits: {}
        get_pull_request: {}
      memory-server:
        search_long_term_memory: {}
        get_long_term_memory: {}

  # Support assistant - tickets and memory, no code access
  support:
    description: "Support tools for ticket management"
    tools:
      zendesk:
        # Include all Zendesk tools
        search_tickets: {}
        get_ticket: {}
        create_ticket: {}
        update_ticket: {}
        add_comment: {}
      memory-server:
        search_long_term_memory: {}
        create_long_term_memories: {}
        edit_long_term_memory: {}

  # Code reviewer - read GitHub + quality analysis, no writes
  reviewer:
    description: "Code review tools - read-only with quality analysis"
    tools:
      github:
        search_code: {}
        get_file_contents: {}
        list_pull_requests: {}
        get_pull_request: {}
        get_pull_request_files: {}
        get_pull_request_status: {}
    custom_tools:
      - module: tools.mfcqi.analyze_code_quality
```

### Accessing Views

**Via stdio** (default view):
```bash
mcp-proxy serve --config config.yaml
```

**Via HTTP** (view-specific endpoints):
```bash
mcp-proxy serve --config config.yaml --transport http --port 8000

# Each view gets its own endpoint:
# http://localhost:8000/view/developer/mcp
# http://localhost:8000/view/explorer/mcp
# http://localhost:8000/view/support/mcp
# http://localhost:8000/view/reviewer/mcp
```

### Exposure Modes

Views support two exposure modes:

**Direct mode** (default): Tools are exposed with their names directly
```yaml
tool_views:
  my-view:
    exposure_mode: direct  # Default
    tools:
      github:
        search_code: {}  # Exposed as "search_code"
```

**Search mode**: Exposes `search_tools` and `call_tool` meta-tools for dynamic
tool discovery
```yaml
tool_views:
  dynamic-view:
    exposure_mode: search
    include_all: true
    # AI can search for tools and call them dynamically
```

### Key Points

1. **`include_all: true`**: Shorthand to include all tools from all servers

2. **Selective inclusion**: List specific tools under each server to create
   curated subsets

3. **Custom tools per view**: Each view can have its own set of custom Python
   tools

4. **HTTP routing**: When serving via HTTP, each view gets a dedicated endpoint

5. **Combine with renaming**: Tools can be renamed within views for
   domain-specific naming

---

## Custom Python Tools with MFCQI

This example shows how to create **custom Python tools** that integrate external
CLIs or libraries. We'll wrap [MFCQI](https://github.com/abrookins/mfcqi)
(Multi-Factor Code Quality Index) to give AI assistants the ability to analyze
code quality.

### The Problem

You have a CLI tool or Python library that you want to expose as an MCP tool.
The tool doesn't have an MCP server, but you want AI assistants to be able to
use it.

### The Solution

Create a custom Python tool using the `@custom_tool` decorator. The tool can:

- Run external commands via `asyncio.subprocess`
- Call Python libraries directly
- Access upstream MCP tools via `ProxyContext`
- Return structured data to the AI

### Step 1: Create the Custom Tool

Create a file `tools/mfcqi.py`:

```python
"""MFCQI code quality analysis tool."""

import asyncio

from mcp_proxy.custom_tools import custom_tool


@custom_tool(
    name="analyze_code_quality",
    description="""Analyze code quality using MFCQI (Multi-Factor Code Quality Index).

Returns comprehensive metrics including:
- Cyclomatic & Cognitive Complexity
- Halstead Volume
- Maintainability Index
- Code Duplication
- Documentation Coverage
- Security Score
- Dependency Security
- Secrets Exposure
- Code Smell Density
- OOP Metrics: RFC, DIT, MHF, CBO, LCOM

Use this to assess code quality, identify areas for improvement, or validate
that code meets quality thresholds before merging.

By default runs in metrics-only mode (no LLM). Set skip_llm=False to get
AI-powered recommendations.""",
)
async def analyze_code_quality(
    path: str,
    min_score: float = 0.7,
    skip_llm: bool = True,
    output_format: str = "terminal",
    quality_gate: bool = False,
    recommendations: int = 5,
    cwd: str = "",
) -> dict:
    """Run MFCQI analysis on a codebase.

    Args:
        path: Path to the directory or file to analyze (required)
        min_score: Minimum acceptable MFCQI score threshold (default: 0.7)
        skip_llm: Skip LLM analysis, metrics only (default: True)
        output_format: Output format - terminal, json, html, markdown, sarif
        quality_gate: Enable quality gates (exit 1 if gates fail)
        recommendations: Number of AI recommendations (if LLM enabled)
        cwd: Working directory to run the command from (optional)

    Returns:
        Analysis results including metrics breakdown and overall score
    """
    cmd = ["uvx", "mfcqi", "analyze", path]

    if min_score:
        cmd.extend(["--min-score", str(min_score)])

    if skip_llm:
        cmd.append("--skip-llm")

    if output_format and output_format != "terminal":
        cmd.extend(["--format", output_format])

    if quality_gate:
        cmd.append("--quality-gate")

    if not skip_llm and recommendations:
        cmd.extend(["--recommendations", str(recommendations)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd if cwd else None,
    )
    stdout, stderr = await proc.communicate()

    return {
        "output": stdout.decode(),
        "stderr": stderr.decode() if stderr else None,
        "return_code": proc.returncode,
        "success": proc.returncode == 0,
    }
```

### Step 2: Register in Configuration

Add the custom tool to a view in your `config.yaml`:

```yaml
tool_views:
  default:
    description: "Default view with code quality analysis"
    include_all: true
    custom_tools:
      - module: tools.mfcqi.analyze_code_quality
```

### Step 3: Use the Tool

Now AI assistants can analyze code quality:

```
User: Analyze the code quality of the src/ directory

AI: I'll analyze the code quality using MFCQI.
    [Calls analyze_code_quality with path="src/"]

    The analysis shows:
    - Overall MFCQI Score: 0.82 (Good)
    - Cyclomatic Complexity: 12.3 avg
    - Maintainability Index: 78
    - Documentation Coverage: 65%
    - No security issues detected
```

### Advanced: Using ProxyContext

Custom tools can also call upstream MCP tools via `ProxyContext`:

```python
from mcp_proxy.custom_tools import custom_tool, ProxyContext


@custom_tool(
    name="smart_analysis",
    description="Analyze code and save findings to memory"
)
async def smart_analysis(path: str, ctx: ProxyContext) -> dict:
    """Analyze code and persist interesting findings."""
    import subprocess

    # Run local analysis
    result = subprocess.run(
        ["uvx", "mfcqi", "analyze", path, "--format", "json"],
        capture_output=True, text=True
    )

    # Save findings to memory via upstream MCP tool
    if ctx:
        await ctx.call_tool(
            "redis-memory-server.create_long_term_memories",
            memories=[{
                "text": f"Code quality analysis for {path}: {result.stdout[:500]}"
            }]
        )

    return {"analysis": result.stdout, "saved_to_memory": True}
```

### Key Points

1. **`@custom_tool` decorator**: Marks a function as an MCP tool with name and
   description

2. **Type hints**: Function parameters are automatically converted to JSON
   schema based on type hints

3. **Async support**: Tools can be async for non-blocking I/O operations

4. **ProxyContext**: Optional parameter that gives access to upstream tools

5. **Return values**: Return a dict that will be serialized as the tool result

---

## More Examples

See the [README.md](README.md) for additional examples including:

- **Parallel composition**: Fan-out tools that call multiple upstreams
- **Pre/post hooks**: Intercept and modify tool calls
- **Tool views**: Named configurations for different use cases
- **HTTP transport**: Serve tools over HTTP with view-based routing

