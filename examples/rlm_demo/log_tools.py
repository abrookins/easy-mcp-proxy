"""Custom MCP tool for retrieving log data.

This tool is used by the RLM demo to demonstrate output caching.
When exposed through different views, the same tool produces:
- Raw output (full log content)
- Cached output (preview + signed URL)
"""

from pathlib import Path

from mcp_proxy.custom_tools import custom_tool

# Path to the generated log file
LOG_FILE = Path(__file__).parent / "logs.ndjson"


@custom_tool(
    name="get_logs",
    description="Retrieve application logs. Returns NDJSON log entries with "
    "timestamps, levels (INFO, DEBUG, WARN, ERROR, FATAL), and message details.",
)
async def get_logs() -> str:
    """Read and return the log file contents.

    This is intentionally simple - just returns the raw file.
    The proxy's output caching handles the rest.
    """
    if not LOG_FILE.exists():
        return '{"error": "Log file not found. Run generate_logs.py first."}'

    return LOG_FILE.read_text()
