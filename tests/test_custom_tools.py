"""Tests for custom tools (Python-defined composite tools)."""

import pytest


class TestCustomToolDecorator:
    """Tests for the @custom_tool decorator."""

    def test_custom_tool_decorator_registers_function(self):
        """@custom_tool should mark a function as a custom tool."""
        from mcp_proxy.custom_tools import custom_tool

        @custom_tool(
            name="my_custom_tool",
            description="A custom tool"
        )
        async def my_tool(query: str) -> dict:
            return {"result": query}

        assert my_tool._is_custom_tool is True
        assert my_tool._tool_name == "my_custom_tool"
        assert my_tool._tool_description == "A custom tool"

    def test_custom_tool_preserves_signature(self):
        """@custom_tool should preserve the function signature."""
        from mcp_proxy.custom_tools import custom_tool
        import inspect

        @custom_tool(name="test", description="Test")
        async def my_tool(query: str, limit: int = 10) -> dict:
            return {}

        sig = inspect.signature(my_tool)
        params = list(sig.parameters.keys())

        assert "query" in params
        assert "limit" in params

    def test_custom_tool_infers_schema(self):
        """@custom_tool should infer JSON schema from type hints."""
        from mcp_proxy.custom_tools import custom_tool

        @custom_tool(name="test", description="Test")
        async def my_tool(query: str, count: int, enabled: bool = True) -> dict:
            return {}

        schema = my_tool._input_schema

        assert schema["properties"]["query"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["enabled"]["type"] == "boolean"
        assert "query" in schema.get("required", [])
        assert "count" in schema.get("required", [])
        assert "enabled" not in schema.get("required", [])


class TestProxyContext:
    """Tests for ProxyContext (injected into custom tools)."""

    async def test_proxy_context_call_tool(self):
        """ProxyContext.call_tool() calls an upstream tool."""
        from mcp_proxy.custom_tools import ProxyContext

        # Mock upstream clients
        call_log = []

        async def mock_call(tool_name, **kwargs):
            call_log.append((tool_name, kwargs))
            return {"result": "mocked"}

        ctx = ProxyContext(call_tool_fn=mock_call)
        result = await ctx.call_tool(
            "redis-memory-server.search_long_term_memory",
            text="query"
        )

        assert result == {"result": "mocked"}
        assert call_log[0] == (
            "redis-memory-server.search_long_term_memory",
            {"text": "query"}
        )

    async def test_proxy_context_available_tools(self):
        """ProxyContext should list available upstream tools."""
        from mcp_proxy.custom_tools import ProxyContext

        available = [
            "server.tool_a",
            "server.tool_b",
        ]

        ctx = ProxyContext(
            call_tool_fn=lambda *a, **k: None,
            available_tools=available
        )

        assert ctx.available_tools == available


class TestCustomToolExecution:
    """Tests for executing custom tools."""

    async def test_custom_tool_receives_context(self):
        """Custom tool should receive ProxyContext as ctx parameter."""
        from mcp_proxy.custom_tools import custom_tool, ProxyContext

        received_ctx = None

        @custom_tool(name="test", description="Test")
        async def my_tool(query: str, ctx: ProxyContext) -> dict:
            nonlocal received_ctx
            received_ctx = ctx
            return {"query": query}

        # When executed through the proxy, ctx should be injected
        # This would need integration with MCPProxy

    async def test_custom_tool_calls_multiple_upstreams(self):
        """Custom tool can orchestrate multiple upstream calls."""
        from mcp_proxy.custom_tools import custom_tool, ProxyContext

        call_sequence = []

        async def mock_call(tool_name, **kwargs):
            call_sequence.append(tool_name)
            return {"data": f"from {tool_name}"}

        @custom_tool(name="composite", description="Composite tool")
        async def composite_tool(query: str, ctx: ProxyContext) -> dict:
            result_a = await ctx.call_tool("server.tool_a", query=query)
            result_b = await ctx.call_tool("server.tool_b", input=result_a["data"])
            return {"combined": [result_a, result_b]}

        ctx = ProxyContext(call_tool_fn=mock_call)
        # Would need to test execution through proxy


class TestCustomToolRegistration:
    """Tests for registering custom tools in a view."""

    def test_custom_tools_loaded_from_module_path(self):
        """Custom tools should be loadable from module paths."""
        from mcp_proxy.custom_tools import load_custom_tool

        # Would load from "hooks.custom_tools.my_tool"
        # Needs actual module to test

    def test_custom_tools_appear_in_view(self):
        """Custom tools should appear alongside upstream tools in a view."""
        from mcp_proxy.views import ToolView
        from mcp_proxy.models import ToolViewConfig

        config = ToolViewConfig(
            custom_tools=[
                {"module": "hooks.custom.my_tool"}
            ]
        )
        view = ToolView("test", config)

        # After initialization, custom tools should be in the tools list

