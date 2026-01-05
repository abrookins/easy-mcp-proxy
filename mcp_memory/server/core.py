"""Core MCP server creation function for the memory system.

Provides the main entry point for creating an MCP server with memory tools.
"""

# ruff: noqa: E501

from fastmcp import FastMCP

from mcp_memory.models import MemoryConfig
from mcp_memory.search import MemorySearcher
from mcp_memory.storage import MemoryStorage

from .artifact_tools import register_artifact_tools
from .concept_tools import register_concept_tools
from .instructions import SERVER_INSTRUCTIONS
from .project_tools import register_project_tools
from .reflection_tools import register_reflection_tools
from .skill_tools import register_skill_tools
from .thread_tools import register_thread_tools


def create_memory_server(
    base_path: str = ".",
    name: str = "MCP Memory",
    config: MemoryConfig | None = None,
    embedding_model=None,
) -> FastMCP:
    """Create an MCP server with memory tools.

    Args:
        base_path: Base path for storage (ignored if config provided)
        name: Name for the MCP server
        config: Optional MemoryConfig (if not provided, uses base_path)
        embedding_model: Optional pre-loaded sentence transformer model (for testing)
    """
    if config is None:
        config = MemoryConfig(base_path=base_path)
    storage = MemoryStorage(config)
    searcher = MemorySearcher(storage, config, model=embedding_model)

    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS)

    # Register all tool groups
    register_thread_tools(mcp, storage, searcher)
    register_concept_tools(mcp, storage, searcher)
    register_reflection_tools(mcp, storage, searcher)
    register_project_tools(mcp, storage, searcher)
    register_skill_tools(mcp, storage, searcher)
    register_artifact_tools(mcp, storage, searcher)

    # Register index management tool
    @mcp.tool()
    def rebuild_index() -> dict:
        """Regenerate the semantic search index from all stored content. Only needed if search results seem stale or after bulk imports. This is an expensive operation—use sparingly."""
        searcher.build_index()
        return {"rebuilt": True, "items": len(searcher._id_map)}

    return mcp
