"""Tests for configuration models (Pydantic)."""

import pytest

from mcp_proxy.config import load_config
from mcp_proxy.models import (
    HooksConfig,
    ProxyConfig,
    ServerToolsConfig,
    ToolConfig,
    ToolViewConfig,
    UpstreamServerConfig,
)


class TestToolConfig:
    """Tests for ToolConfig model."""

    def test_tool_config_defaults(self):
        """ToolConfig should have sensible defaults."""
        config = ToolConfig()
        assert config.name is None
        assert config.description is None
        assert config.enabled is True

    def test_tool_config_with_name(self):
        """ToolConfig should accept a name for renaming."""
        config = ToolConfig(name="renamed_tool")
        assert config.name == "renamed_tool"

    def test_tool_config_with_description(self):
        """ToolConfig should accept a description override."""
        config = ToolConfig(description="Custom description. {original}")
        assert "{original}" in config.description

    def test_tool_config_disabled(self):
        """ToolConfig can disable a tool."""
        config = ToolConfig(enabled=False)
        assert config.enabled is False


class TestHooksConfig:
    """Tests for HooksConfig model."""

    def test_hooks_config_defaults(self):
        """HooksConfig should default to no hooks."""
        config = HooksConfig()
        assert config.pre_call is None
        assert config.post_call is None

    def test_hooks_config_with_paths(self):
        """HooksConfig should accept dotted paths to hook functions."""
        config = HooksConfig(
            pre_call="hooks.auth.pre_call", post_call="hooks.logging.post_call"
        )
        assert config.pre_call == "hooks.auth.pre_call"
        assert config.post_call == "hooks.logging.post_call"


class TestToolViewConfig:
    """Tests for ToolViewConfig model."""

    def test_tool_view_config_defaults(self):
        """ToolViewConfig should have sensible defaults."""
        config = ToolViewConfig()
        assert config.description is None
        assert config.exposure_mode == "direct"
        assert config.tools == {}
        assert config.hooks is None

    def test_tool_view_config_search_mode(self):
        """ToolViewConfig can be set to search exposure mode."""
        config = ToolViewConfig(exposure_mode="search")
        assert config.exposure_mode == "search"

    def test_tool_view_config_with_tools(self):
        """ToolViewConfig should nest server/tool configs."""
        config = ToolViewConfig(
            tools={
                "server1": {
                    "tool_a": ToolConfig(name="renamed_a"),
                    "tool_b": ToolConfig(),
                }
            }
        )
        assert "server1" in config.tools
        assert config.tools["server1"]["tool_a"].name == "renamed_a"

    def test_tool_view_config_include_all(self):
        """ToolViewConfig can include all tools from all servers."""
        config = ToolViewConfig(include_all=True)
        assert config.include_all is True


class TestServerToolsConfig:
    """Tests for ServerToolsConfig (nested tool dict)."""

    def test_server_tools_config_structure(self):
        """ServerToolsConfig maps tool names to ToolConfig."""
        # ServerToolsConfig is essentially dict[str, ToolConfig]
        config = ServerToolsConfig(
            root={
                "tool_a": ToolConfig(name="renamed"),
                "tool_b": ToolConfig(description="Custom desc"),
            }
        )
        assert "tool_a" in config.root
        assert config.root["tool_a"].name == "renamed"


class TestUpstreamServerConfig:
    """Tests for UpstreamServerConfig model."""

    def test_command_based_server(self):
        """UpstreamServerConfig can define a command-based server."""
        config = UpstreamServerConfig(command="uv", args=["tool", "run", "server"])
        assert config.command == "uv"
        assert config.args == ["tool", "run", "server"]
        assert config.url is None

    def test_url_based_server(self):
        """UpstreamServerConfig can define a URL-based server."""
        config = UpstreamServerConfig(url="http://localhost:8080/mcp")
        assert config.url == "http://localhost:8080/mcp"
        assert config.command is None

    def test_command_server_with_env(self):
        """UpstreamServerConfig can include environment variables."""
        config = UpstreamServerConfig(
            command="server",
            env={"REDIS_URL": "redis://localhost:6379", "DEBUG": "true"},
        )
        assert config.env["REDIS_URL"] == "redis://localhost:6379"
        assert config.env["DEBUG"] == "true"

    def test_command_server_with_cwd(self):
        """UpstreamServerConfig can include working directory."""
        config = UpstreamServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/data"],
            cwd="/data",
        )
        assert config.cwd == "/data"
        assert config.command == "npx"

    def test_url_server_with_headers(self):
        """UpstreamServerConfig can include HTTP headers."""
        config = UpstreamServerConfig(
            url="https://api.example.com/mcp",
            headers={"Authorization": "Bearer token123"},
        )
        assert config.headers["Authorization"] == "Bearer token123"


class TestProxyConfig:
    """Tests for ProxyConfig (root config) model."""

    def test_proxy_config_structure(self):
        """ProxyConfig should contain servers and views."""
        config = ProxyConfig(
            mcp_servers={"server1": {"command": "echo"}},
            tool_views={"view1": {"description": "Test"}},
        )
        assert "server1" in config.mcp_servers
        assert "view1" in config.tool_views

    def test_load_config_from_yaml(self, sample_config_yaml):
        """ProxyConfig should load from a YAML file."""
        config = load_config(sample_config_yaml)
        assert "test-server" in config.mcp_servers
        assert "test-view" in config.tool_views
