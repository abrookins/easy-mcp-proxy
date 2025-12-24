"""Tests for custom tools (Python-defined composite tools)."""

import inspect
import sys

import pytest

from mcp_proxy.custom_tools import ProxyContext, custom_tool, load_custom_tool


class TestCustomToolDecorator:
    """Tests for the @custom_tool decorator."""

    def test_custom_tool_decorator_registers_function(self):
        """@custom_tool should mark a function as a custom tool."""

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

        @custom_tool(name="test", description="Test")
        async def my_tool(query: str, limit: int = 10) -> dict:
            return {}

        sig = inspect.signature(my_tool)
        params = list(sig.parameters.keys())

        assert "query" in params
        assert "limit" in params

    def test_custom_tool_infers_schema(self):
        """@custom_tool should infer JSON schema from type hints."""

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
        available = [
            "server.tool_a",
            "server.tool_b",
        ]

        ctx = ProxyContext(
            call_tool_fn=lambda *a, **k: None,
            available_tools=available
        )

        assert ctx.available_tools == available

    async def test_proxy_context_call_tool_without_fn_raises(self):
        """ProxyContext.call_tool() raises RuntimeError if no call_tool_fn."""
        ctx = ProxyContext()

        with pytest.raises(RuntimeError, match="No call_tool_fn configured"):
            await ctx.call_tool("some.tool", arg="value")

    def test_proxy_context_list_tools(self):
        """ProxyContext.list_tools() returns available tools list."""
        available = ["server.tool_a", "server.tool_b", "server.tool_c"]

        ctx = ProxyContext(available_tools=available)

        assert ctx.list_tools() == available

    def test_proxy_context_list_tools_empty(self):
        """ProxyContext.list_tools() returns empty list by default."""
        ctx = ProxyContext()

        assert ctx.list_tools() == []


class TestCustomToolExecution:
    """Tests for executing custom tools."""

    async def test_custom_tool_receives_context(self):
        """Custom tool should receive ProxyContext as ctx parameter."""
        received_ctx = None

        @custom_tool(name="test", description="Test")
        async def my_tool(query: str, ctx: ProxyContext = None) -> dict:
            nonlocal received_ctx
            received_ctx = ctx
            return {"query": query}

        # Execute the tool with a context
        ctx = ProxyContext(call_tool_fn=lambda *a, **k: None)
        result = await my_tool(query="hello", ctx=ctx)

        assert received_ctx is ctx
        assert result == {"query": "hello"}

    async def test_custom_tool_calls_multiple_upstreams(self):
        """Custom tool can orchestrate multiple upstream calls."""
        call_sequence = []

        async def mock_call(tool_name, **kwargs):
            call_sequence.append(tool_name)
            return {"data": f"from {tool_name}"}

        @custom_tool(name="composite", description="Composite tool")
        async def composite_tool(query: str, ctx: ProxyContext = None) -> dict:
            result_a = await ctx.call_tool("server.tool_a", query=query)
            result_b = await ctx.call_tool("server.tool_b", input=result_a["data"])
            return {"combined": [result_a, result_b]}

        ctx = ProxyContext(call_tool_fn=mock_call)
        result = await composite_tool(query="test", ctx=ctx)

        assert call_sequence == ["server.tool_a", "server.tool_b"]
        assert result["combined"][0] == {"data": "from server.tool_a"}
        assert result["combined"][1] == {"data": "from server.tool_b"}


class TestCustomToolRegistration:
    """Tests for registering custom tools in a view."""

    def test_custom_tools_loaded_from_module_path(self, tmp_path, monkeypatch):
        """Custom tools should be loadable from module paths."""
        # Create a temporary module with a custom tool
        module_dir = tmp_path / "test_module"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "tools.py").write_text('''
from mcp_proxy.custom_tools import custom_tool

@custom_tool(name="test_tool", description="A test tool")
async def my_test_tool(query: str) -> dict:
    return {"result": query}
''')

        # Add to sys.path so we can import it
        monkeypatch.syspath_prepend(str(tmp_path))

        # Load the custom tool
        tool = load_custom_tool("test_module.tools.my_test_tool")

        assert tool._is_custom_tool is True
        assert tool._tool_name == "test_tool"
        assert tool._tool_description == "A test tool"

    def test_load_custom_tool_rejects_non_custom_functions(self, tmp_path, monkeypatch):
        """load_custom_tool should reject functions without @custom_tool decorator."""
        # Create a module with a regular function
        module_dir = tmp_path / "regular_module"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "funcs.py").write_text('''
async def regular_function(x: int) -> int:
    return x * 2
''')

        monkeypatch.syspath_prepend(str(tmp_path))

        with pytest.raises(ValueError, match="is not a custom tool"):
            load_custom_tool("regular_module.funcs.regular_function")

    def test_custom_tools_appear_in_view(self, tmp_path, monkeypatch):
        """Custom tools should appear alongside upstream tools in a view."""
        from mcp_proxy.models import ToolViewConfig
        from mcp_proxy.views import ToolView

        # Create a test custom tool module
        module_dir = tmp_path / "hooks"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "custom.py").write_text('''
from mcp_proxy.custom_tools import custom_tool

@custom_tool(name="my_tool", description="My custom tool")
async def my_tool(x: str) -> dict:
    return {"result": x}
''')
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(
            custom_tools=[
                {"module": "hooks.custom.my_tool"}
            ]
        )
        view = ToolView("test", config)

        # Verify the config was stored
        assert len(config.custom_tools) == 1
        assert config.custom_tools[0]["module"] == "hooks.custom.my_tool"

        # Verify the tool was loaded into the view
        assert "my_tool" in view.custom_tools
