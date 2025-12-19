"""Tests for parallel/fan-out tool execution."""

import pytest
import asyncio


class TestParallelToolConfig:
    """Tests for parallel tool configuration."""

    def test_parallel_tool_from_config(self):
        """ParallelTool should be creatable from config."""
        from mcp_proxy.parallel import ParallelTool

        config = {
            "description": "Search all sources",
            "inputs": {
                "query": {"type": "string", "required": True}
            },
            "parallel": {
                "memory": {
                    "tool": "redis.search_long_term_memory",
                    "args": {"text": "{inputs.query}"}
                },
                "code": {
                    "tool": "github.search_code",
                    "args": {"query": "{inputs.query}"}
                }
            }
        }

        parallel_tool = ParallelTool.from_config("search_all", config)

        assert parallel_tool.name == "search_all"
        assert parallel_tool.description == "Search all sources"
        assert len(parallel_tool.parallel_steps) == 2

    def test_parallel_tool_input_schema(self):
        """ParallelTool should generate correct input schema."""
        from mcp_proxy.parallel import ParallelTool

        config = {
            "inputs": {
                "query": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False}
            },
            "parallel": {}
        }

        parallel_tool = ParallelTool.from_config("test", config)
        schema = parallel_tool.input_schema

        assert schema["properties"]["query"]["type"] == "string"
        assert "query" in schema["required"]
        assert "limit" not in schema["required"]


class TestParallelToolExecution:
    """Tests for parallel tool execution."""

    async def test_parallel_executes_concurrently(self):
        """Parallel tool should execute all steps concurrently."""
        from mcp_proxy.parallel import ParallelTool

        execution_times = {}

        async def mock_call(tool_name, **kwargs):
            start = asyncio.get_event_loop().time()
            await asyncio.sleep(0.1)  # Simulate network delay
            execution_times[tool_name] = asyncio.get_event_loop().time() - start
            return {"tool": tool_name, "args": kwargs}

        config = {
            "inputs": {"query": {"type": "string"}},
            "parallel": {
                "a": {"tool": "server.tool_a", "args": {"q": "{inputs.query}"}},
                "b": {"tool": "server.tool_b", "args": {"q": "{inputs.query}"}},
                "c": {"tool": "server.tool_c", "args": {"q": "{inputs.query}"}},
            }
        }

        parallel_tool = ParallelTool.from_config("test", config)
        parallel_tool._call_tool_fn = mock_call

        start = asyncio.get_event_loop().time()
        result = await parallel_tool.execute({"query": "test"})
        total_time = asyncio.get_event_loop().time() - start

        # If parallel, total time should be ~0.1s, not ~0.3s
        assert total_time < 0.25  # Allow some overhead
        assert "a" in result
        assert "b" in result
        assert "c" in result

    async def test_parallel_returns_named_results(self):
        """Parallel tool should return results keyed by step name."""
        from mcp_proxy.parallel import ParallelTool

        async def mock_call(tool_name, **kwargs):
            return {"from": tool_name}

        config = {
            "inputs": {"query": {"type": "string"}},
            "parallel": {
                "memory": {"tool": "redis.search", "args": {}},
                "code": {"tool": "github.search", "args": {}},
            }
        }

        parallel_tool = ParallelTool.from_config("test", config)
        parallel_tool._call_tool_fn = mock_call

        result = await parallel_tool.execute({"query": "test"})

        assert result["memory"]["from"] == "redis.search"
        assert result["code"]["from"] == "github.search"

    async def test_parallel_template_resolution(self):
        """Parallel tool should resolve input templates in args."""
        from mcp_proxy.parallel import ParallelTool

        captured_args = {}

        async def mock_call(tool_name, **kwargs):
            captured_args[tool_name] = kwargs
            return {}

        config = {
            "inputs": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "parallel": {
                "a": {
                    "tool": "server.tool",
                    "args": {
                        "text": "{inputs.query}",
                        "max_results": "{inputs.limit}"
                    }
                }
            }
        }

        parallel_tool = ParallelTool.from_config("test", config)
        parallel_tool._call_tool_fn = mock_call

        await parallel_tool.execute({"query": "hello", "limit": 5})

        assert captured_args["server.tool"]["text"] == "hello"
        assert captured_args["server.tool"]["max_results"] == 5


class TestParallelToolErrorHandling:
    """Tests for error handling in parallel execution."""

    async def test_parallel_collects_all_errors(self):
        """Parallel tool should report which steps failed."""
        from mcp_proxy.parallel import ParallelTool

        async def mock_call(tool_name, **kwargs):
            if tool_name == "server.fail":
                raise Exception("Simulated failure")
            return {"ok": True}

        config = {
            "inputs": {},
            "parallel": {
                "good": {"tool": "server.good", "args": {}},
                "bad": {"tool": "server.fail", "args": {}},
            }
        }

        parallel_tool = ParallelTool.from_config("test", config)
        parallel_tool._call_tool_fn = mock_call

        result = await parallel_tool.execute({})

        assert result["good"]["ok"] is True
        assert "error" in result["bad"]

