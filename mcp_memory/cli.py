"""CLI for MCP Memory server."""

import click


def load_config(path: str, config_file: str | None = None):
    """Load config from file or create default."""
    from pathlib import Path

    import yaml

    from mcp_memory.models import MemoryConfig

    # Look for config file
    config_path = None
    if config_file:
        config_path = Path(config_file)
    else:
        # Auto-detect config file in path
        base = Path(path)
        for name in [".mcp-memory.yaml", ".mcp-memory.yml", "mcp-memory.yaml"]:
            if (base / name).exists():
                config_path = base / name
                break

    if config_path and config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        # Ensure base_path is set
        if "base_path" not in data:
            data["base_path"] = path
        return MemoryConfig.model_validate(data)

    return MemoryConfig(base_path=path)


@click.group()
def main():
    """MCP Memory - Portable LLM memory using markdown files."""
    pass  # pragma: no cover


@main.command()
@click.option(
    "--path",
    "-p",
    default=".",
    help="Base path for memory storage (default: current directory)",
)
@click.option(
    "--config",
    "-c",
    default=None,
    help="Path to config file (auto-detects .mcp-memory.yaml)",
)
@click.option(
    "--transport",
    "-t",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport type (default: stdio)",
)
@click.option(
    "--port",
    default=8000,
    help="Port for HTTP transport (default: 8000)",
)
def serve(path: str, config: str | None, transport: str, port: int):
    """Start the MCP Memory server."""
    from mcp_memory.server import create_memory_server

    memory_config = load_config(path, config)
    server = create_memory_server(config=memory_config)

    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="sse", port=port)


@main.command()
@click.option(
    "--path",
    "-p",
    default=".",
    help="Base path for memory storage",
)
def init(path: str):
    """Initialize a memory directory structure."""
    from pathlib import Path

    from mcp_memory.models import MemoryConfig

    config = MemoryConfig(base_path=path)
    base = Path(path)

    dirs = [
        config.threads_dir,
        config.concepts_dir,
        config.projects_dir,
        config.skills_dir,
        config.reflections_dir,
    ]

    for d in dirs:
        (base / d).mkdir(parents=True, exist_ok=True)
        click.echo(f"Created {base / d}")

    click.echo("Memory directory initialized!")


@main.command()
@click.option(
    "--path",
    "-p",
    default=".",
    help="Base path for memory storage",
)
def build_index(path: str):
    """Build or rebuild the search index."""
    from mcp_memory.models import MemoryConfig
    from mcp_memory.search import MemorySearcher
    from mcp_memory.storage import MemoryStorage

    config = MemoryConfig(base_path=path)
    storage = MemoryStorage(config)
    searcher = MemorySearcher(storage, config)

    click.echo("Building search index...")
    searcher.build_index()
    click.echo(f"Index built with {len(searcher._id_map)} items")


if __name__ == "__main__":
    main()
