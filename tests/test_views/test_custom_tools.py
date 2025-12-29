"""Tests for custom tool error handling."""

import pytest

from mcp_proxy.models import ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolViewCustomToolErrors:
    """Tests for custom tool error handling."""

    async def test_custom_tool_call_upstream_unknown_tool_raises(
        self, tmp_path, monkeypatch
    ):
        """Custom tool calling unknown upstream should raise."""
        # Create a custom tool that tries to call an unknown upstream
        module_dir = tmp_path / "test_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_unknown", description="Tries to call unknown tool")
async def call_unknown(ctx: ProxyContext, query: str) -> dict:
    # Try to call a tool that doesn't exist with wrong format
    return await ctx.call_tool("no_dot_format", query=query)
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "test_hooks.tools.call_unknown"}]
        )
        view = ToolView("test", config)
        view._upstream_clients = {}

        with pytest.raises(ValueError, match="Unknown upstream tool"):
            await view.call_tool("call_unknown", {"query": "test"})

    async def test_custom_tool_call_upstream_unknown_server_raises(
        self, tmp_path, monkeypatch
    ):
        """Custom tool calling tool on unknown server should raise."""
        # Create a custom tool that calls a tool with proper format but unknown server
        module_dir = tmp_path / "unknown_server_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_unknown_server", description="Calls unknown server")
async def call_unknown_server(ctx: ProxyContext, query: str) -> dict:
    # Try to call a tool on a server that doesn't exist
    return await ctx.call_tool("missing_server.tool", query=query)
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "unknown_server_hooks.tools.call_unknown_server"}]
        )
        view = ToolView("test", config)
        view._upstream_clients = {
            "other_server": None
        }  # Has a server, but not the one we call

        with pytest.raises(ValueError, match="Unknown upstream tool"):
            await view.call_tool("call_unknown_server", {"query": "test"})

    async def test_custom_tool_calls_upstream_successfully(self, tmp_path, monkeypatch):
        """Custom tool calling valid upstream should work."""
        from unittest.mock import AsyncMock

        # Create a custom tool that calls a valid upstream
        module_dir = tmp_path / "success_hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.custom_tools import ProxyContext

@custom_tool(name="call_valid", description="Calls valid upstream")
async def call_valid(ctx: ProxyContext, query: str) -> dict:
    result = await ctx.call_tool("server.search", query=query)
    return {"wrapped": result}
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[{"module": "success_hooks.tools.call_valid"}]
        )
        view = ToolView("test", config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "from upstream"}
        view._upstream_clients = {"server": mock_client}

        result = await view.call_tool("call_valid", {"query": "test"})

        assert "wrapped" in result
        mock_client.call_tool.assert_called_with("search", {"query": "test"})

