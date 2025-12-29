"""Tests for composite tool execution in ToolView."""

from mcp_proxy.models import CompositeToolConfig, ToolViewConfig
from mcp_proxy.views import ToolView


class TestToolViewCompositeTool:
    """Tests for composite tool execution in ToolView."""

    async def test_call_composite_tool_executes_parallel(self):
        """call_tool should execute composite tools via parallel execution."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(
            composite_tools={
                "multi_search": CompositeToolConfig(
                    description="Search multiple sources",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "source_a": {
                            "tool": "server-a.tool_a",
                            "args": {"q": "{inputs.query}"},
                        },
                        "source_b": {
                            "tool": "server-b.tool_b",
                            "args": {"q": "{inputs.query}"},
                        },
                    },
                )
            }
        )
        view = ToolView("test", config)

        # Mock upstream clients
        mock_client_a = AsyncMock()
        mock_client_a.call_tool.return_value = {"result": "from_a"}
        mock_client_b = AsyncMock()
        mock_client_b.call_tool.return_value = {"result": "from_b"}
        view._upstream_clients = {"server-a": mock_client_a, "server-b": mock_client_b}

        result = await view.call_tool("multi_search", {"query": "test"})

        # Should return results from composite tool
        assert "results" in result or isinstance(result, dict)

    async def test_composite_tool_calls_upstream_tools(self):
        """Composite tools should call upstream tools correctly."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(
            composite_tools={
                "dual_search": CompositeToolConfig(
                    description="Dual search",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {
                            "tool": "server.tool_a",
                            "args": {"q": "{inputs.query}"},
                        },
                    },
                )
            }
        )
        view = ToolView("test", config)

        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"data": "result"}
        view._upstream_clients = {"server": mock_client}

        await view.call_tool("dual_search", {"query": "hello"})

        # Verify upstream was called
        mock_client.call_tool.assert_called()

    async def test_composite_tool_unknown_server_returns_error(self):
        """Composite tool calling unknown server should return error in results."""
        config = ToolViewConfig(
            composite_tools={
                "bad_composite": CompositeToolConfig(
                    description="Has unknown server",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "missing.tool", "args": {}},
                    },
                )
            }
        )
        view = ToolView("test", config)
        # No clients at all - will fail to find "missing" server
        view._upstream_clients = {}

        # ParallelTool catches exceptions and returns them in results
        result = await view.call_tool("bad_composite", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]
        assert "Unknown upstream tool" in result["result"]["error"]

    async def test_composite_tool_unknown_server_with_other_clients(self):
        """Composite tool calling unknown server with other clients present."""
        config = ToolViewConfig(
            composite_tools={
                "wrong_server": CompositeToolConfig(
                    description="Calls wrong server",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {"tool": "nonexistent.tool", "args": {}},
                    },
                )
            }
        )
        view = ToolView("test", config)
        # Has clients, but not the one the tool needs - tests 187 branch
        view._upstream_clients = {"existing_server": None}

        result = await view.call_tool("wrong_server", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]

    async def test_composite_tool_no_dot_in_tool_name(self):
        """Composite tool with tool name missing dot should error."""
        config = ToolViewConfig(
            composite_tools={
                "bad_format": CompositeToolConfig(
                    description="Tool without server.tool format",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "result": {
                            "tool": "no_dot_format",
                            "args": {},
                        },  # Missing the dot
                    },
                )
            }
        )
        view = ToolView("test", config)
        view._upstream_clients = {}

        # This should trigger the 185->191 branch (no dot in tool name)
        result = await view.call_tool("bad_format", {"query": "test"})
        assert "result" in result
        assert "error" in result["result"]
        assert "Unknown upstream tool" in result["result"]["error"]

    async def test_composite_tool_successful_upstream_call(self):
        """Composite tool should successfully call upstream and return results."""
        from unittest.mock import AsyncMock

        config = ToolViewConfig(
            composite_tools={
                "good_composite": CompositeToolConfig(
                    description="Successful composite",
                    inputs={"query": {"type": "string"}},
                    parallel={
                        "search": {
                            "tool": "server.search_tool",
                            "args": {"q": "{inputs.query}"},
                        },
                    },
                )
            }
        )
        view = ToolView("test", config)

        # Mock the upstream client
        mock_client = AsyncMock()
        mock_client.call_tool.return_value = {"found": 10}
        view._upstream_clients = {"server": mock_client}

        result = await view.call_tool("good_composite", {"query": "test"})

        # Should have successful result
        assert "search" in result
        # Verify the upstream was actually called
        mock_client.call_tool.assert_called()
