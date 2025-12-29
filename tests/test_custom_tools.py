"""Tests for custom tools (Python-defined composite tools)."""

import inspect

import pytest

from mcp_proxy.custom_tools import ProxyContext, custom_tool, load_custom_tool


class TestCustomToolDecorator:
    """Tests for the @custom_tool decorator."""

    def test_custom_tool_decorator_registers_function(self):
        """@custom_tool should mark a function as a custom tool."""

        @custom_tool(name="my_custom_tool", description="A custom tool")
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
            "redis-memory-server.search_long_term_memory", text="query"
        )

        assert result == {"result": "mocked"}
        assert call_log[0] == (
            "redis-memory-server.search_long_term_memory",
            {"text": "query"},
        )

    async def test_proxy_context_available_tools(self):
        """ProxyContext should list available upstream tools."""
        available = [
            "server.tool_a",
            "server.tool_b",
        ]

        ctx = ProxyContext(call_tool_fn=lambda *a, **k: None, available_tools=available)

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
        (module_dir / "tools.py").write_text("""
from mcp_proxy.custom_tools import custom_tool

@custom_tool(name="test_tool", description="A test tool")
async def my_test_tool(query: str) -> dict:
    return {"result": query}
""")

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
        (module_dir / "funcs.py").write_text("""
async def regular_function(x: int) -> int:
    return x * 2
""")

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
        (module_dir / "custom.py").write_text("""
from mcp_proxy.custom_tools import custom_tool

@custom_tool(name="my_tool", description="My custom tool")
async def my_tool(x: str) -> dict:
    return {"result": x}
""")
        monkeypatch.syspath_prepend(str(tmp_path))

        config = ToolViewConfig(custom_tools=[{"module": "hooks.custom.my_tool"}])
        view = ToolView("test", config)

        # Verify the config was stored
        assert len(config.custom_tools) == 1
        assert config.custom_tools[0]["module"] == "hooks.custom.my_tool"

        # Verify the tool was loaded into the view
        assert "my_tool" in view.custom_tools


class TestMFCQITool:
    """Tests for the MFCQI code quality analysis tool."""

    def test_mfcqi_tool_is_registered(self):
        """The analyze_code_quality tool should be properly decorated."""
        from mcp_proxy.tools.mfcqi import analyze_code_quality

        assert analyze_code_quality._is_custom_tool is True
        assert analyze_code_quality._tool_name == "analyze_code_quality"
        assert "MFCQI" in analyze_code_quality._tool_description

    def test_mfcqi_tool_schema(self):
        """The tool should have correct input schema."""
        from mcp_proxy.tools.mfcqi import analyze_code_quality

        schema = analyze_code_quality._input_schema

        # Required parameters
        assert "project_path" in schema["properties"]
        assert "project_path" in schema.get("required", [])

        # Optional parameters with defaults
        assert "min_score" in schema["properties"]
        assert "skip_llm" in schema["properties"]
        assert "output_format" in schema["properties"]
        assert "quality_gate" in schema["properties"]
        assert "recommendations" in schema["properties"]

        # These should not be required (have defaults)
        assert "min_score" not in schema.get("required", [])
        assert "skip_llm" not in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_mfcqi_tool_builds_command(self, monkeypatch):
        """The tool should build the correct uvx command."""
        from mcp_proxy.tools.mfcqi import analyze_code_quality

        captured_cmd = None
        captured_cwd = None

        async def mock_subprocess(*args, stdout=None, stderr=None, cwd=None):
            nonlocal captured_cmd, captured_cwd
            captured_cmd = args
            captured_cwd = cwd

            class MockProc:
                returncode = 0

                async def communicate(self):
                    return (b"mock output", b"")

            return MockProc()

        monkeypatch.setattr(
            "mcp_proxy.tools.mfcqi.asyncio.create_subprocess_exec", mock_subprocess
        )

        result = await analyze_code_quality(
            project_path="/some/project",
            min_score=0.8,
            skip_llm=True,
        )

        assert captured_cmd == (
            "uvx",
            "mfcqi",
            "analyze",
            "/some/project",
            "--min-score",
            "0.8",
            "--skip-llm",
        )
        assert result["success"] is True
        assert result["output"] == "mock output"

    @pytest.mark.asyncio
    async def test_mfcqi_tool_with_llm_enabled(self, monkeypatch):
        """The tool should include recommendations when LLM is enabled."""
        from mcp_proxy.tools.mfcqi import analyze_code_quality

        captured_cmd = None

        async def mock_subprocess(*args, stdout=None, stderr=None, cwd=None):
            nonlocal captured_cmd
            captured_cmd = args

            class MockProc:
                returncode = 0

                async def communicate(self):
                    return (b"", b"")

            return MockProc()

        monkeypatch.setattr(
            "mcp_proxy.tools.mfcqi.asyncio.create_subprocess_exec", mock_subprocess
        )

        await analyze_code_quality(
            project_path="/project",
            skip_llm=False,
            recommendations=10,
        )

        assert "--skip-llm" not in captured_cmd
        assert "--recommendations" in captured_cmd
        assert "10" in captured_cmd

    @pytest.mark.asyncio
    async def test_mfcqi_tool_handles_failure(self, monkeypatch):
        """The tool should report failure when command fails."""
        from mcp_proxy.tools.mfcqi import analyze_code_quality

        async def mock_subprocess(*args, stdout=None, stderr=None, cwd=None):
            class MockProc:
                returncode = 1

                async def communicate(self):
                    return (b"", b"Error: invalid path")

            return MockProc()

        monkeypatch.setattr(
            "mcp_proxy.tools.mfcqi.asyncio.create_subprocess_exec", mock_subprocess
        )

        result = await analyze_code_quality(project_path="/nonexistent")

        assert result["success"] is False
        assert result["return_code"] == 1
        assert result["stderr"] == "Error: invalid path"
