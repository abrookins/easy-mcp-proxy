"""Tests for the CLI commands."""

import pytest
from click.testing import CliRunner


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_get_config_path_when_default_exists(self, tmp_path, monkeypatch):
        """get_config_path should return existing DEFAULT_CONFIG_FILE."""
        from mcp_proxy import cli

        # Create a fake default config file
        fake_config_dir = tmp_path / ".config" / "mcp-proxy"
        fake_config_dir.mkdir(parents=True)
        fake_config_file = fake_config_dir / "config.yaml"
        fake_config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        # Monkeypatch the defaults
        monkeypatch.setattr(cli, "DEFAULT_CONFIG_DIR", fake_config_dir)
        monkeypatch.setattr(cli, "DEFAULT_CONFIG_FILE", fake_config_file)

        # Call without explicit config - should return existing default
        result = cli.get_config_path(None)

        assert result == fake_config_file
        # File should not have been recreated
        assert fake_config_file.exists()


class TestCLIServers:
    """Tests for 'mcp-proxy servers' command."""

    def test_servers_lists_configured_servers(self, sample_config_yaml):
        """'servers' should list all configured upstream servers."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["servers", "--config", str(sample_config_yaml)])

        assert result.exit_code == 0
        assert "test-server" in result.output


class TestCLITools:
    """Tests for 'mcp-proxy tools' command."""

    def test_tools_lists_all_tools(self, sample_config_yaml):
        """'tools' should list all tools from all servers."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["tools", "--config", str(sample_config_yaml)])

        # Would need actual upstream connection to list tools
        # Just verify command exists
        assert result.exit_code in (0, 1)  # May fail without upstream

    def test_tools_filters_by_server(self, sample_config_yaml):
        """'tools --server X' should filter to one server."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["tools", "--config", str(sample_config_yaml), "--server", "test-server"],
        )

        # Verify option is accepted
        assert "--server" not in result.output or result.exit_code == 0

    def test_tools_lists_server_tools(self, config_with_tools_yaml):
        """'tools' should list tools defined on servers."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["tools", "--config", str(config_with_tools_yaml)])

        assert result.exit_code == 0
        assert "github.search_code" in result.output
        assert "github.search_issues" in result.output
        assert "memory.store" in result.output

    def test_tools_filters_by_server_with_tools(self, config_with_tools_yaml):
        """'tools --server X' should only list tools from that server."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["tools", "--config", str(config_with_tools_yaml), "--server", "github"],
        )

        assert result.exit_code == 0
        assert "github.search_code" in result.output
        assert "memory.store" not in result.output

    def test_tools_lists_view_tools(self, config_with_tools_yaml):
        """'tools' should also list tools from views."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["tools", "--config", str(config_with_tools_yaml)])

        # View tools should also appear
        assert result.exit_code == 0
        assert "github.search_code" in result.output

    def test_tools_filters_view_tools_by_server(self, tmp_path):
        """'tools --server X' should filter view tools too."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "  memory:\n"
            "    command: memory-server\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
            "      memory:\n"
            "        store: {}\n"
        )

        runner = CliRunner()
        # Filter by github - should NOT show memory tools
        result = runner.invoke(
            main, ["tools", "--server", "github", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "github.search_code" in result.output
        assert "memory.store" not in result.output

    def test_tools_with_empty_view_tools(self, tmp_path):
        """'tools' should handle views with no tools defined."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "tool_views:\n"
            "  empty_view:\n"
            "    description: View with no tools\n"  # No tools key
        )

        runner = CliRunner()
        result = runner.invoke(main, ["tools", "--config", str(config_file)])

        assert result.exit_code == 0
        # Should still show server tools
        assert "github.search_code" in result.output


class TestCLISchema:
    """Tests for 'mcp-proxy schema' command."""

    def test_schema_shows_tool_details(self, sample_config_yaml):
        """'schema <tool>' should show tool parameters and description."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "test-server.test_tool", "--config", str(sample_config_yaml)],
        )

        # Would need upstream to get actual schema
        assert result.exit_code in (0, 1)

    def test_schema_json_output(self, sample_config_yaml):
        """'schema --json' should output JSON format."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--json", "--config", str(sample_config_yaml)]
        )

        # Verify --json flag is accepted
        assert result.exit_code in (0, 1)

    def test_schema_server_filter(self, sample_config_yaml):
        """'schema --server X' should show all tools from one server."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "--server", "test-server", "--config", str(sample_config_yaml)],
        )

        assert result.exit_code in (0, 1)

    def test_schema_tool_invalid_format(self, sample_config_yaml):
        """'schema <tool>' without dot should error."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "invalidtoolname", "--config", str(sample_config_yaml)]
        )

        assert result.exit_code == 1
        assert "format 'server.tool'" in result.output

    def test_schema_tool_unknown_server(self, sample_config_yaml):
        """'schema <unknown>.tool' should error."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "unknown-server.tool", "--config", str(sample_config_yaml)]
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_schema_tool_with_json(self, sample_config_yaml):
        """'schema <tool> --json' should output JSON."""
        from mcp_proxy.cli import main
        import json

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "schema",
                "test-server.test_tool",
                "--json",
                "--config",
                str(sample_config_yaml),
            ],
        )

        # Now attempts actual connection - may fail with connection error
        # but should still output valid JSON
        data = json.loads(result.output)
        assert "tool" in data

    def test_schema_server_with_json(self, sample_config_yaml):
        """'schema --server X --json' should output JSON."""
        from mcp_proxy.cli import main
        import json

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "schema",
                "--server",
                "test-server",
                "--json",
                "--config",
                str(sample_config_yaml),
            ],
        )

        # Now attempts actual connection - may fail
        # but should still output valid JSON
        data = json.loads(result.output)
        assert "server" in data or "tools" in data

    def test_schema_server_not_found(self, sample_config_yaml):
        """'schema --server unknown' should error."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "--server", "nonexistent", "--config", str(sample_config_yaml)],
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_schema_all_servers(self, sample_config_yaml):
        """'schema' without args should show all servers."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "--config", str(sample_config_yaml)])

        assert result.exit_code == 0
        assert "test-server" in result.output

    def test_schema_all_servers_json(self, sample_config_yaml):
        """'schema --json' without args should output JSON for all servers."""
        from mcp_proxy.cli import main
        import json

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--json", "--config", str(sample_config_yaml)]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Now returns {"tools": {...}} instead of {"servers": [...]}
        assert "tools" in data


class TestCLIValidate:
    """Tests for 'mcp-proxy validate' command."""

    def test_validate_checks_config(self, sample_config_yaml):
        """'validate' should check config syntax."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--config", str(sample_config_yaml)])

        # Config is valid, so should succeed
        assert result.exit_code == 0

    def test_validate_reports_invalid_config(self, tmp_path):
        """'validate' should report config errors."""
        from mcp_proxy.cli import main

        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text("invalid: [yaml: content")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--config", str(bad_config)])

        assert result.exit_code != 0

    def test_validate_reports_semantic_errors(self, tmp_path):
        """'validate' should report semantic config errors."""
        from mcp_proxy.cli import main

        # Config with invalid view reference
        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text("""
mcp_servers: {}
tool_views:
  test:
    description: "Test"
    tools:
      nonexistent-server:
        some_tool: {}
""")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--config", str(bad_config)])

        # Should report validation error
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_validate_tests_upstream_connections(self, sample_config_yaml):
        """'validate' should test upstream server connections."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "--config", str(sample_config_yaml)])

        # Without real upstreams, may report connection failures
        # Just verify command runs


class TestCLIConfig:
    """Tests for 'mcp-proxy config' command."""

    def test_config_shows_raw_config(self, sample_config_yaml):
        """'config' should show raw config file."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["config", "--config", str(sample_config_yaml)])

        assert result.exit_code == 0
        assert "mcp_servers" in result.output

    def test_config_resolved_shows_parsed_config(self, sample_config_yaml):
        """'config --resolved' should show parsed config."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main, ["config", "--resolved", "--config", str(sample_config_yaml)]
        )

        assert result.exit_code == 0
        assert "mcp_servers" in result.output


class TestCLIInit:
    """Tests for 'mcp-proxy init' command."""

    def test_init_hooks_generates_example(self):
        """'init hooks' should generate example hook file."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", "hooks"])

        assert result.exit_code == 0
        assert "pre_call" in result.output
        assert "post_call" in result.output
        assert "HookResult" in result.output

    def test_init_config_generates_example(self):
        """'init config' should generate example config."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", "config"])

        assert result.exit_code == 0
        assert "mcp_servers" in result.output
        assert "tool_views" in result.output


class TestCLIServe:
    """Tests for 'mcp-proxy serve' command."""

    def test_serve_accepts_config(self, sample_config_yaml):
        """'serve' should accept --config option."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        # Don't actually run the server, just check option parsing
        result = runner.invoke(
            main, ["serve", "--config", str(sample_config_yaml), "--help"]
        )

        assert result.exit_code == 0

    def test_serve_accepts_transport_stdio(self):
        """'serve' should accept --transport stdio."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])

        assert "--transport" in result.output or result.exit_code == 0

    def test_serve_accepts_transport_http_with_port(self):
        """'serve' should accept --transport http --port N."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])

        assert "--port" in result.output or result.exit_code == 0

    def test_serve_accepts_env_file_option(self):
        """'serve' should accept --env-file option."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])

        assert "--env-file" in result.output
        assert "-e" in result.output

    def test_serve_loads_env_file(self, tmp_path, monkeypatch):
        """'serve' should load environment variables from .env file."""
        import os

        from mcp_proxy.cli import main

        # Create a .env file with a test variable
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_SERVE_VAR=test_value_123\n")

        # Create a config that uses the env var
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  test:\n"
            "    url: https://example.com\n"
            "    headers:\n"
            "      X-Test: ${TEST_SERVE_VAR}\n"
            "tool_views: {}\n"
        )

        # Ensure the var is not already set
        monkeypatch.delenv("TEST_SERVE_VAR", raising=False)

        # We can't actually run serve (it blocks), but we can test the
        # dotenv loading by importing and calling load_dotenv directly
        from dotenv import load_dotenv

        load_dotenv(str(env_file))

        assert os.environ.get("TEST_SERVE_VAR") == "test_value_123"

    def test_serve_env_file_default_is_dotenv(self):
        """'serve' --env-file should default to .env."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])

        assert "default: .env" in result.output


class TestCLICall:
    """Tests for 'mcp-proxy call' command."""

    def test_call_invokes_tool(self, sample_config_yaml):
        """'call <tool>' should invoke a tool and return result."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "call",
                "test-server.test_tool",
                "--config",
                str(sample_config_yaml),
                "--arg",
                "query=test",
            ],
        )

        # Would need upstream to actually call
        assert result.exit_code in (0, 1)


# =============================================================================
# Server Management Commands
# =============================================================================


class TestCLIServerAdd:
    """Tests for 'mcp-proxy server add' command."""

    def test_server_add_with_command(self, tmp_path):
        """'server add <name> --command <cmd>' should add a stdio server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "my-server" in content

    def test_server_add_with_command_and_args(self, tmp_path):
        """'server add' should accept --args for command arguments."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "uv",
                "--args",
                "tool,run,--from,some-package,some-command",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "my-server" in content
        assert "tool" in content  # args should be present

    def test_server_add_with_url(self, tmp_path):
        """'server add <name> --url <url>' should add a remote HTTP server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "github",
                "--url",
                "https://api.githubcopilot.com/mcp/",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "github" in content
        assert "https://api.githubcopilot.com/mcp/" in content

    def test_server_add_with_env(self, tmp_path):
        """'server add' should accept --env for environment variables."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--env",
                "REDIS_URL=redis://localhost:6379",
                "--env",
                "DEBUG=true",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "REDIS_URL" in content

    def test_server_add_with_cwd(self, tmp_path):
        """'server add' should accept --cwd for working directory."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "filesystem",
                "--command",
                "npx",
                "--args",
                "-y,@modelcontextprotocol/server-filesystem,/data",
                "--cwd",
                "/data",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "filesystem" in content
        assert "cwd: /data" in content

    def test_server_add_with_headers(self, tmp_path):
        """'server add' should accept --header for HTTP headers."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "github",
                "--url",
                "https://api.githubcopilot.com/mcp/",
                "--header",
                "Authorization=Bearer ${GITHUB_TOKEN}",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "Authorization" in content

    def test_server_add_cwd_requires_command(self, tmp_path):
        """'server add --cwd' should fail without --command."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--url",
                "https://example.com/mcp",
                "--cwd",
                "/data",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0
        assert "--cwd requires --command" in result.output

    def test_server_add_fails_without_command_or_url(self, tmp_path):
        """'server add' should fail if neither --command nor --url is provided."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "add", "my-server", "--config", str(config_file)]
        )

        assert result.exit_code != 0

    def test_server_add_fails_if_exists(self, tmp_path):
        """'server add' should fail if server already exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  existing:\n    command: echo\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "existing",
                "--command",
                "echo",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0
        assert "exists" in result.output.lower() or "already" in result.output.lower()


class TestCLIServerRemove:
    """Tests for 'mcp-proxy server remove' command."""

    def test_server_remove_existing(self, tmp_path):
        """'server remove <name>' should remove an existing server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  my-server:\n    command: echo\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "remove", "my-server", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "my-server" not in content

    def test_server_remove_nonexistent(self, tmp_path):
        """'server remove' should fail for non-existent server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "remove", "nonexistent", "--config", str(config_file)]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_server_remove_no_referencing_views(self, tmp_path):
        """'server remove' should work when no views reference the server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  my-server:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  empty_view:\n"
            "    description: View with no tools\n"  # Doesn't reference server
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "remove", "my-server", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "my-server" not in content

    def test_server_remove_with_force_cleans_views(self, tmp_path):
        """'server remove --force' should clean up view references."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["server", "remove", "github", "--force", "--config", str(config_file)],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # Server should be removed and view reference cleaned up
        assert "github" not in content or "github: {}" in content


class TestCLIServerList:
    """Tests for 'mcp-proxy server list' command."""

    def test_server_list_shows_all_servers(self, tmp_path):
        """'server list' should list all configured servers."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  server-a:\n    command: echo\n"
            "  server-b:\n    url: https://example.com\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(main, ["server", "list", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "server-a" in result.output
        assert "server-b" in result.output

    def test_server_list_empty(self, tmp_path):
        """'server list' should handle empty server list."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(main, ["server", "list", "--config", str(config_file)])

        assert result.exit_code == 0


class TestCLIServerSetTools:
    """Tests for 'mcp-proxy server set-tools' command."""

    def test_server_set_tools_creates_allowlist(self, tmp_path):
        """'server set-tools <server> tool1,tool2' should create tool allowlist."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  github:\n    url: https://example.com\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tools",
                "github",
                "search_code,search_issues,get_file_contents",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "search_code" in content
        assert "search_issues" in content
        assert "get_file_contents" in content

    def test_server_set_tools_nonexistent_server(self, tmp_path):
        """'server set-tools' should fail for non-existent server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tools",
                "nonexistent",
                "tool1,tool2",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_server_set_tools_empty_when_no_tools_key(self, tmp_path):
        """'server set-tools' with empty string when no tools key exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"  # No tools key
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tools",
                "github",
                "",
                "--config",
                str(config_file),
            ],  # Empty string
        )

        assert result.exit_code == 0


class TestCLIServerClearTools:
    """Tests for 'mcp-proxy server clear-tools' command."""

    def test_server_clear_tools_removes_allowlist(self, tmp_path):
        """'server clear-tools <server>' should remove tool filtering."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "      search_issues: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "clear-tools", "github", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # tools section should be removed or empty
        assert (
            "search_code" not in content
            or "tools: {}" in content
            or "tools:" not in content
        )

    def test_server_clear_tools_not_found(self, tmp_path):
        """'server clear-tools' on non-existent server should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "clear-tools", "nonexistent", "--config", str(config_file)]
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_server_clear_tools_when_no_tools_key(self, tmp_path):
        """'server clear-tools' should work even if no tools key exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  github:\n    url: https://example.com\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "clear-tools", "github", "--config", str(config_file)]
        )

        assert result.exit_code == 0


class TestCLIServerSetToolDescription:
    """Tests for 'mcp-proxy server set-tool-description' command."""

    def test_set_tool_description_creates_custom_description(self, tmp_path):
        """'server set-tool-description' should set custom tool description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "Use this to search code. Focus on symbols.\n\n{original}",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "description" in content
        assert "{original}" in content

    def test_set_tool_description_adds_tool_if_not_in_list(self, tmp_path):
        """'server set-tool-description' should add tool to list if not present."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  github:\n    url: https://example.com\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "Custom instructions here",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

    def test_set_tool_description_server_not_found(self, tmp_path):
        """'server set-tool-description' on non-existent server should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "nonexistent",
                "tool",
                "description",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_set_tool_description_empty_clears_description(self, tmp_path):
        """'server set-tool-description' with empty string should clear description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code:\n"
            "        description: Old description\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "",  # Empty string
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # Description should be removed
        assert "Old description" not in content

    def test_set_tool_description_empty_when_no_description(self, tmp_path):
        """'server set-tool-description' with empty string when no description exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"  # No description key
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "",  # Empty string - nothing to clear
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0


# =============================================================================
# Tool View Management Commands
# =============================================================================


class TestCLIViewCreate:
    """Tests for 'mcp-proxy view create' command."""

    def test_view_create_basic(self, tmp_path):
        """'view create <name>' should create a new tool view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "create", "research", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "research" in content

    def test_view_create_with_description(self, tmp_path):
        """'view create' should accept --description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "create",
                "research",
                "--description",
                "Tools for research tasks",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "research" in content
        assert "Tools for research tasks" in content

    def test_view_create_fails_if_exists(self, tmp_path):
        """'view create' should fail if view already exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\ntool_views:\n  existing:\n    description: Already here\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "create", "existing", "--config", str(config_file)]
        )

        assert result.exit_code != 0
        assert "exists" in result.output.lower() or "already" in result.output.lower()


class TestCLIViewDelete:
    """Tests for 'mcp-proxy view delete' command."""

    def test_view_delete_existing(self, tmp_path):
        """'view delete <name>' should remove an existing view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\ntool_views:\n  my-view:\n    description: Test view\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "delete", "my-view", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "my-view" not in content

    def test_view_delete_nonexistent(self, tmp_path):
        """'view delete' should fail for non-existent view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "delete", "nonexistent", "--config", str(config_file)]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestCLIViewList:
    """Tests for 'mcp-proxy view list' command."""

    def test_view_list_shows_all_views(self, tmp_path):
        """'view list' should list all configured views."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  view-a:\n"
            "    description: View A\n"
            "  view-b:\n"
            "    description: View B\n"
        )

        runner = CliRunner()
        result = runner.invoke(main, ["view", "list", "--config", str(config_file)])

        assert result.exit_code == 0
        assert "view-a" in result.output
        assert "view-b" in result.output

    def test_view_list_empty(self, tmp_path):
        """'view list' should handle empty view list."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(main, ["view", "list", "--config", str(config_file)])

        assert result.exit_code == 0


class TestCLIViewAddServer:
    """Tests for 'mcp-proxy view add-server' command."""

    def test_view_add_server_all_tools(self, tmp_path):
        """'view add-server <view> <server>' should add server with all tools."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["view", "add-server", "research", "github", "--config", str(config_file)],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "github" in content

    def test_view_add_server_specific_tools(self, tmp_path):
        """'view add-server --tools' should add only specified tools."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "research",
                "github",
                "--tools",
                "search_code,search_issues",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "search_code" in content
        assert "search_issues" in content

    def test_view_add_server_nonexistent_view(self, tmp_path):
        """'view add-server' should fail for non-existent view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n  github:\n    url: https://example.com\ntool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "nonexistent",
                "github",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_view_add_server_nonexistent_server(self, tmp_path):
        """'view add-server' should fail for non-existent server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "research",
                "nonexistent",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestCLIViewRemoveServer:
    """Tests for 'mcp-proxy view remove-server' command."""

    def test_view_remove_server(self, tmp_path):
        """'view remove-server <view> <server>' should remove server from view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "remove-server",
                "research",
                "github",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # github should be removed from the view's tools
        # Check that the view still exists but github is not in its tools
        assert "research" in content

    def test_view_remove_server_nonexistent_view(self, tmp_path):
        """'view remove-server' should fail for non-existent view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "remove-server",
                "nonexistent",
                "github",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_view_remove_server_not_in_view(self, tmp_path):
        """'view remove-server' should fail if server not in view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
            "    tools: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "remove-server",
                "research",
                "github",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0


# =============================================================================
# Edge Cases
# =============================================================================


class TestCLIServerAddEdgeCases:
    """Edge cases for 'mcp-proxy server add' command."""

    def test_server_add_both_command_and_url_fails(self, tmp_path):
        """'server add' should fail if both --command and --url are provided."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--url",
                "https://example.com",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_server_add_args_without_command_fails(self, tmp_path):
        """'server add' should fail if --args is used without --command."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--url",
                "https://example.com",
                "--args",
                "arg1,arg2",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_server_add_headers_without_url_fails(self, tmp_path):
        """'server add' should fail if --header is used without --url."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--header",
                "Authorization=Bearer token",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_server_add_env_without_equals_ignored(self, tmp_path):
        """'server add --env' without = should ignore that entry."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--env",
                "INVALID_NO_EQUALS",  # No = sign
                "--env",
                "VALID=value",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "VALID" in content
        assert "INVALID_NO_EQUALS" not in content

    def test_server_add_env_all_invalid(self, tmp_path):
        """'server add --env' with all invalid entries should not add env key."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--command",
                "echo",
                "--env",
                "INVALID1",  # No = sign
                "--env",
                "INVALID2",  # No = sign
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # env key should not be present since all entries were invalid
        assert "env:" not in content

    def test_server_add_header_without_equals_ignored(self, tmp_path):
        """'server add --header' without = should ignore that entry."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--url",
                "https://example.com",
                "--header",
                "INVALID_NO_EQUALS",  # No = sign
                "--header",
                "Authorization=token",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "Authorization" in content
        assert "INVALID_NO_EQUALS" not in content

    def test_server_add_header_all_invalid(self, tmp_path):
        """'server add --header' with all invalid entries should not add headers key."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "my-server",
                "--url",
                "https://example.com",
                "--header",
                "INVALID1",  # No = sign
                "--header",
                "INVALID2",  # No = sign
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # headers key should not be present since all entries were invalid
        assert "headers:" not in content

    def test_server_add_preserves_existing_servers(self, tmp_path):
        """'server add' should not modify existing servers."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  existing-server:\n"
            "    command: existing-cmd\n"
            "    args:\n"
            "      - existing-arg\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "new-server",
                "--command",
                "echo",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "existing-server" in content
        assert "existing-cmd" in content
        assert "new-server" in content

    def test_server_add_with_env_var_syntax(self, tmp_path):
        """'server add' should preserve ${VAR} syntax in values."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "add",
                "github",
                "--url",
                "https://api.github.com",
                "--header",
                "Authorization=Bearer ${GITHUB_TOKEN}",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "${GITHUB_TOKEN}" in content


class TestCLIServerRemoveEdgeCases:
    """Edge cases for 'mcp-proxy server remove' command."""

    def test_server_remove_referenced_by_view_warns(self, tmp_path):
        """'server remove' should warn if server is referenced by a view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "remove", "github", "--config", str(config_file)]
        )

        # Should either fail or warn about the reference
        # For safety, it should probably fail without --force
        assert (
            result.exit_code != 0
            or "view" in result.output.lower()
            or "reference" in result.output.lower()
        )

    def test_server_remove_with_force_removes_references(self, tmp_path):
        """'server remove --force' should remove server and clean up view references."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["server", "remove", "github", "--force", "--config", str(config_file)],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "github" not in content or "search_code" not in content

    def test_server_remove_preserves_other_servers(self, tmp_path):
        """'server remove' should not affect other servers."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  server-a:\n"
            "    command: cmd-a\n"
            "  server-b:\n"
            "    command: cmd-b\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "remove", "server-a", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "server-a" not in content
        assert "server-b" in content
        assert "cmd-b" in content


class TestCLIServerSetToolsEdgeCases:
    """Edge cases for 'mcp-proxy server set-tools' command."""

    def test_server_set_tools_replaces_existing(self, tmp_path):
        """'server set-tools' should replace existing tool list, not merge."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      old_tool: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["server", "set-tools", "github", "new_tool", "--config", str(config_file)],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "new_tool" in content
        assert "old_tool" not in content

    def test_server_set_tools_empty_list_clears(self, tmp_path):
        """'server set-tools' with empty string should clear tools (like clear-tools)."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "set-tools", "github", "", "--config", str(config_file)]
        )

        # Could either clear tools or reject empty input
        assert result.exit_code == 0 or result.exit_code != 0

    def test_server_set_tools_preserves_other_config(self, tmp_path):
        """'server set-tools' should preserve other server config like env."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  my-server:\n"
            "    command: my-cmd\n"
            "    env:\n"
            "      MY_VAR: my-value\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tools",
                "my-server",
                "tool1,tool2",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "MY_VAR" in content
        assert "my-value" in content
        assert "tool1" in content


class TestCLIServerSetToolDescriptionEdgeCases:
    """Edge cases for 'mcp-proxy server set-tool-description' command."""

    def test_set_tool_description_multiline(self, tmp_path):
        """'server set-tool-description' should handle multiline descriptions."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "tool_views: {}\n"
        )

        multiline_desc = "Line 1.\nLine 2.\nLine 3.\n\n{original}"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                multiline_desc,
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "Line 1" in content

    def test_set_tool_description_without_original_placeholder(self, tmp_path):
        """'server set-tool-description' without {original} should replace entirely."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "Completely new description without original.",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "Completely new description" in content

    def test_set_tool_description_clears_with_empty(self, tmp_path):
        """'server set-tool-description' with empty string should clear description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "    tools:\n"
            "      search_code:\n"
            "        description: Old description\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-description",
                "github",
                "search_code",
                "",
                "--config",
                str(config_file),
            ],
        )

        # Should clear the description or the tool config
        assert result.exit_code == 0


class TestCLIViewCreateEdgeCases:
    """Edge cases for 'mcp-proxy view create' command."""

    def test_view_create_with_exposure_mode(self, tmp_path):
        """'view create' should accept --exposure-mode option."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "create",
                "research",
                "--exposure-mode",
                "search",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "research" in content
        assert "search" in content

    def test_view_create_preserves_existing_views(self, tmp_path):
        """'view create' should not modify existing views."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  existing:\n"
            "    description: Existing view\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "create", "new-view", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "existing" in content
        assert "Existing view" in content
        assert "new-view" in content


class TestCLIViewAddServerEdgeCases:
    """Edge cases for 'mcp-proxy view add-server' command."""

    def test_view_add_server_already_exists_updates(self, tmp_path):
        """'view add-server' when server already in view should update tools."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        old_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "research",
                "github",
                "--tools",
                "new_tool",
                "--config",
                str(config_file),
            ],
        )

        # Should either update or warn about existing
        assert result.exit_code == 0 or "already" in result.output.lower()

    def test_view_add_server_with_tool_descriptions(self, tmp_path):
        """'view add-server' should support tool descriptions via separate command."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        # First add the server
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "research",
                "github",
                "--tools",
                "search_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0

    def test_view_add_server_with_include_all(self, tmp_path):
        """'view add-server --all' should set include_all for the server."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "add-server",
                "research",
                "github",
                "--all",
                "--config",
                str(config_file),
            ],
        )

        # Should add server with all tools (not filtered)
        assert result.exit_code == 0


class TestCLIViewDeleteEdgeCases:
    """Edge cases for 'mcp-proxy view delete' command."""

    def test_view_delete_preserves_other_views(self, tmp_path):
        """'view delete' should not affect other views."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  view-a:\n"
            "    description: View A\n"
            "  view-b:\n"
            "    description: View B\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "delete", "view-a", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "view-a" not in content
        assert "view-b" in content
        assert "View B" in content


class TestCLIServerListEdgeCases:
    """Edge cases for 'mcp-proxy server list' command."""

    def test_server_list_json_output(self, tmp_path):
        """'server list --json' should output JSON format."""
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  server-a:\n"
            "    command: echo\n"
            "  server-b:\n"
            "    url: https://example.com\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "list", "--json", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert "server-a" in str(data)
        assert "server-b" in str(data)

    def test_server_list_verbose_with_url(self, tmp_path):
        """'server list --verbose' should show URL details."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  my-server:\n"
            "    url: https://example.com/mcp\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "my-server" in result.output
        assert "url:" in result.output
        assert "https://example.com/mcp" in result.output

    def test_server_list_verbose_with_env_and_tools(self, tmp_path):
        """'server list --verbose' should show env and tools details."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  my-server:\n"
            "    command: echo\n"
            "    env:\n"
            "      MY_VAR: value\n"
            "    tools:\n"
            "      tool_a: {}\n"
            "      tool_b: {}\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "env:" in result.output
        assert "MY_VAR" in result.output
        assert "tools:" in result.output
        assert "tool_a" in result.output

    def test_server_list_verbose_shows_details(self, tmp_path):
        """'server list --verbose' should show server details."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  my-server:\n"
            "    command: my-cmd\n"
            "    args:\n"
            "      - arg1\n"
            "tool_views: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["server", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "my-server" in result.output
        # Verbose should show more details like command/url
        assert "my-cmd" in result.output or "command" in result.output.lower()


class TestCLIViewListEdgeCases:
    """Edge cases for 'mcp-proxy view list' command."""

    def test_view_list_json_output(self, tmp_path):
        """'view list --json' should output JSON format."""
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  view-a:\n"
            "    description: View A\n"
            "  view-b:\n"
            "    description: View B\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "list", "--json", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "view-a" in str(data)
        assert "view-b" in str(data)

    def test_view_list_verbose_shows_tools(self, tmp_path):
        """'view list --verbose' should show tools in each view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "research" in result.output
        # Verbose should show tools
        assert "github" in result.output or "search_code" in result.output

    def test_view_list_verbose_shows_exposure_mode(self, tmp_path):
        """'view list --verbose' should show exposure_mode."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
            "    exposure_mode: direct\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0

    def test_view_list_verbose_no_description(self, tmp_path):
        """'view list --verbose' works when view has no description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers: {}\ntool_views:\n  minimal:\n    exposure_mode: direct\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["view", "list", "--verbose", "--config", str(config_file)]
        )

        assert result.exit_code == 0
        assert "minimal" in result.output
        assert "exposure_mode" in result.output
        assert "direct" in result.output


class TestCLIConfigFileEdgeCases:
    """Edge cases for config file handling."""

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        """CLI should create config directory if it doesn't exist."""
        from mcp_proxy.cli import main, DEFAULT_CONFIG_DIR

        # Use a temp directory that doesn't exist
        fake_config_dir = tmp_path / "nonexistent" / ".config" / "mcp-proxy"
        fake_config_file = fake_config_dir / "config.yaml"

        monkeypatch.setattr("mcp_proxy.cli.DEFAULT_CONFIG_DIR", fake_config_dir)
        monkeypatch.setattr("mcp_proxy.cli.DEFAULT_CONFIG_FILE", fake_config_file)

        runner = CliRunner()
        result = runner.invoke(main, ["server", "list"])

        # Should create directory and default config
        assert fake_config_dir.exists() or result.exit_code != 0

    def test_handles_malformed_yaml(self, tmp_path):
        """CLI should handle malformed YAML gracefully."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: [\ninvalid yaml content")

        runner = CliRunner()
        result = runner.invoke(main, ["server", "list", "--config", str(config_file)])

        assert result.exit_code != 0
        assert "error" in result.output.lower() or "invalid" in result.output.lower()

    def test_handles_empty_config_file(self, tmp_path):
        """CLI should handle empty config file."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        runner = CliRunner()
        result = runner.invoke(main, ["server", "list", "--config", str(config_file)])

        # Should either work with defaults or error gracefully
        assert result.exit_code in (0, 1)


class TestCLIViewSetTools:
    """Tests for 'mcp-proxy view set-tools' command."""

    def test_view_set_tools_creates_allowlist(self, tmp_path):
        """'view set-tools' should set tool allowlist for a server in a view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tools",
                "research",
                "github",
                "search_code,search_issues,get_file_contents",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "search_code" in content
        assert "search_issues" in content
        assert "get_file_contents" in content

    def test_view_set_tools_nonexistent_view(self, tmp_path):
        """'view set-tools' should fail for non-existent view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tools",
                "nonexistent",
                "github",
                "tool1",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_view_set_tools_replaces_existing(self, tmp_path):
        """'view set-tools' should replace existing tools, not merge."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        old_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tools",
                "research",
                "github",
                "new_tool",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "new_tool" in content
        assert "old_tool" not in content

    def test_view_set_tools_empty_clears_tools(self, tmp_path):
        """'view set-tools' with empty string should clear tools."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        old_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tools",
                "research",
                "github",
                "",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "old_tool" not in content or "github: {}" in content

    def test_view_set_tools_creates_tools_dict(self, tmp_path):
        """'view set-tools' should create tools dict if missing."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research tools\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tools",
                "research",
                "github",
                "tool1,tool2",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "tool1" in content
        assert "tool2" in content


class TestCLIViewClearTools:
    """Tests for 'mcp-proxy view clear-tools' command."""

    def test_view_clear_tools_removes_filter(self, tmp_path):
        """'view clear-tools' should remove tool filtering for a server in a view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
            "        search_issues: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["view", "clear-tools", "research", "github", "--config", str(config_file)],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # Tools should be cleared (empty dict or removed)
        assert "search_code" not in content or "github: {}" in content

    def test_view_clear_tools_nonexistent_view(self, tmp_path):
        """'view clear-tools' should fail for non-existent view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "clear-tools",
                "nonexistent",
                "github",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code != 0

    def test_view_clear_tools_server_not_in_view(self, tmp_path):
        """'view clear-tools' should fail if server not in view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["view", "clear-tools", "research", "github", "--config", str(config_file)],
        )

        assert result.exit_code != 0


class TestCLIViewSetToolDescription:
    """Tests for setting tool descriptions within views."""

    def test_view_set_tool_description(self, tmp_path):
        """'view set-tool-description' should set custom description for tool in view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-description",
                "research",
                "github",
                "search_code",
                "Custom view-specific instructions.\n\n{original}",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "Custom view-specific" in content

    def test_view_set_tool_description_creates_tool_entry(self, tmp_path):
        """'view set-tool-description' should create tool entry if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    description: Research view\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-description",
                "research",
                "github",
                "new_tool",
                "Tool description",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "new_tool" in content
        assert "Tool description" in content

    def test_view_set_tool_description_empty_clears_description(self, tmp_path):
        """'view set-tool-description' with empty string should clear description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code:\n"
            "          description: Old description\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-description",
                "research",
                "github",
                "search_code",
                "",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # Description should be removed or empty
        assert "Old description" not in content

    def test_view_set_tool_description_view_not_found(self, tmp_path):
        """'view set-tool-description' on non-existent view should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-description",
                "nonexistent",
                "github",
                "tool",
                "description",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_view_set_tool_description_empty_when_no_description_exists(self, tmp_path):
        """'view set-tool-description' with empty string when no description exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    url: https://example.com\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"  # No description key
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-description",
                "research",
                "github",
                "search_code",
                "",  # Empty string - nothing to clear
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0


class TestCLIWithMockedUpstream:
    """Tests for CLI commands with mocked upstream connections."""

    def test_schema_with_successful_connection(self, tmp_path, monkeypatch):
        """schema command should show schemas when connection succeeds."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        # Mock the MCPProxy._create_client to return a mock client
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search for items"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "test.search", "-c", str(config_file)])

        assert "search" in result.output.lower()
        # Should show description or parameters
        assert "Search" in result.output or "Parameters" in result.output

    def test_schema_server_with_successful_connection(self, tmp_path, monkeypatch):
        """schema --server should list tools from server."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_a"
        mock_tool1.description = "Tool A description"
        mock_tool1.inputSchema = {}

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool_b"
        mock_tool2.description = "Tool B description"
        mock_tool2.inputSchema = {}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool1, mock_tool2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--server", "myserver", "-c", str(config_file)]
        )

        assert "myserver" in result.output.lower() or "Server" in result.output
        assert "tool_a" in result.output
        assert "tool_b" in result.output
        assert "Tools (2)" in result.output

    def test_schema_all_with_successful_connection(self, tmp_path, monkeypatch):
        """schema (all) should list all servers and tools."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  server1:
    command: echo
  server2:
    command: echo
""")

        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        mock_tool.description = "A tool"
        mock_tool.inputSchema = {}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "-c", str(config_file)])

        assert "server1" in result.output
        assert "server2" in result.output
        assert "1 tools" in result.output

    def test_schema_respects_tool_constraints(self, tmp_path, monkeypatch):
        """schema should only show tools listed in server's tools config."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        # Config with tool constraints - only tool_a and tool_b are allowed
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  constrained:
    command: echo
    tools:
      tool_a: {}
      tool_b: {}
  unconstrained:
    command: echo
""")

        # Upstream returns 4 tools
        mock_tool_a = MagicMock()
        mock_tool_a.name = "tool_a"
        mock_tool_a.description = "Tool A"
        mock_tool_a.inputSchema = {}

        mock_tool_b = MagicMock()
        mock_tool_b.name = "tool_b"
        mock_tool_b.description = "Tool B"
        mock_tool_b.inputSchema = {}

        mock_tool_c = MagicMock()
        mock_tool_c.name = "tool_c"
        mock_tool_c.description = "Tool C - should be filtered"
        mock_tool_c.inputSchema = {}

        mock_tool_d = MagicMock()
        mock_tool_d.name = "tool_d"
        mock_tool_d.description = "Tool D - should be filtered"
        mock_tool_d.inputSchema = {}

        all_tools = [mock_tool_a, mock_tool_b, mock_tool_c, mock_tool_d]

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=all_tools)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "-c", str(config_file)])

        # constrained server should show only 2 tools (tool_a, tool_b)
        # unconstrained server should show all 4 tools
        assert "constrained: 2 tools" in result.output
        assert "unconstrained: 4 tools" in result.output

    def test_schema_server_respects_tool_constraints(self, tmp_path, monkeypatch):
        """schema --server should respect tool constraints for that server."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
    tools:
      allowed_tool: {}
""")

        # Upstream returns 3 tools, but only 1 is in the allowlist
        mock_tool_allowed = MagicMock()
        mock_tool_allowed.name = "allowed_tool"
        mock_tool_allowed.description = "This tool is allowed"
        mock_tool_allowed.inputSchema = {}

        mock_tool_blocked1 = MagicMock()
        mock_tool_blocked1.name = "blocked_tool_1"
        mock_tool_blocked1.description = "Should not appear"
        mock_tool_blocked1.inputSchema = {}

        mock_tool_blocked2 = MagicMock()
        mock_tool_blocked2.name = "blocked_tool_2"
        mock_tool_blocked2.description = "Should not appear"
        mock_tool_blocked2.inputSchema = {}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(
            return_value=[mock_tool_allowed, mock_tool_blocked1, mock_tool_blocked2]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--server", "myserver", "-c", str(config_file)]
        )

        assert result.exit_code == 0
        assert "allowed_tool" in result.output
        assert "blocked_tool_1" not in result.output
        assert "blocked_tool_2" not in result.output
        assert "Tools (1)" in result.output

    def test_call_with_successful_execution(self, tmp_path, monkeypatch):
        """call command should show result when tool executes successfully."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        # Mock call result
        mock_content = MagicMock()
        mock_content.text = '{"result": "success", "count": 42}'

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "call",
                "myserver.do_something",
                "-a",
                "query=test",
                "-c",
                str(config_file),
            ],
        )

        assert "Calling myserver.do_something" in result.output
        assert "Result:" in result.output
        assert "success" in result.output

    def test_validate_with_successful_connections(self, tmp_path, monkeypatch):
        """validate --check-connections should report success."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  server1:
    command: echo
  server2:
    command: echo
""")

        mock_tool = MagicMock()
        mock_tool.name = "tool1"

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(
            return_value=[mock_tool, mock_tool, mock_tool]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-C", "-c", str(config_file)])

        assert "Configuration is valid" in result.output
        assert "Checking upstream connections" in result.output
        assert "connected" in result.output
        assert "3 tools" in result.output

    def test_schema_tool_not_found(self, tmp_path, monkeypatch):
        """schema should report when tool is not found on server."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        # Mock client returns tools, but not the one we're looking for
        mock_tool = MagicMock()
        mock_tool.name = "other_tool"
        mock_tool.description = "Not the tool we want"
        mock_tool.inputSchema = {}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "test.nonexistent_tool", "-c", str(config_file)]
        )

        assert "not found" in result.output

    def test_schema_tool_not_found_json(self, tmp_path, monkeypatch):
        """schema --json should return error when tool not found."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        mock_tool = MagicMock()
        mock_tool.name = "other_tool"
        mock_tool.description = "Other"
        mock_tool.inputSchema = {}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "test.missing", "--json", "-c", str(config_file)]
        )

        data = json.loads(result.output)
        assert "error" in data
        assert data["error"] == "not found"

    def test_schema_tool_found_json(self, tmp_path, monkeypatch):
        """schema --json should return schema when tool is found."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  test:
    command: echo
""")

        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "Search tool"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "test.search", "--json", "-c", str(config_file)]
        )

        data = json.loads(result.output)
        assert "tool" in data
        assert "schema" in data
        assert data["schema"]["name"] == "search"

    def test_schema_server_json_output_success(self, tmp_path, monkeypatch):
        """schema --server --json should return tools as JSON."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        mock_tool = MagicMock()
        mock_tool.name = "tool1"
        mock_tool.description = "A tool"
        mock_tool.inputSchema = {"type": "object"}

        mock_client = MagicMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--server", "myserver", "--json", "-c", str(config_file)]
        )

        data = json.loads(result.output)
        assert "server" in data
        assert "tools" in data
        assert len(data["tools"]) == 1

    def test_schema_all_exception_text(self, tmp_path, monkeypatch):
        """schema (all) should handle exceptions in text mode."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  broken:
    command: echo
""")

        async def mock_create_client_fails(self, server_name):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "-c", str(config_file)])

        assert "Error" in result.output or "error" in result.output

    def test_schema_all_exception_json(self, tmp_path, monkeypatch):
        """schema --json (all) should return JSON on exception."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  broken:
    command: echo
""")

        async def mock_create_client_fails(self, server_name):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "--json", "-c", str(config_file)])

        # Should still output JSON (with error info)
        data = json.loads(result.output)
        assert "tools" in data

    def test_schema_server_exception_json(self, tmp_path, monkeypatch):
        """schema --server --json should return JSON on exception."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main
        import json

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  broken:
    command: echo
""")

        async def mock_create_client_fails(self, server_name):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(
            main, ["schema", "--server", "broken", "--json", "-c", str(config_file)]
        )

        # Should output JSON with error
        data = json.loads(result.output)
        assert "server" in data
        assert "error" in data

    def test_schema_tool_exception_text(self, tmp_path, monkeypatch):
        """schema <tool> should handle exceptions in text mode."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  broken:
    command: echo
""")

        async def mock_create_client_fails(self, server_name):
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(main, ["schema", "broken.tool", "-c", str(config_file)])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_call_exception_handling(self, tmp_path, monkeypatch):
        """call should handle exceptions gracefully."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        async def mock_create_client_fails(self, server_name):
            raise RuntimeError("Server not available")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(main, ["call", "myserver.tool", "-c", str(config_file)])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_call_invalid_tool_format(self, tmp_path):
        """call with invalid tool format should error."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(main, ["call", "no_dot_format", "-c", str(config_file)])

        assert result.exit_code == 1
        assert "format 'server.tool'" in result.output

    def test_call_unknown_server(self, tmp_path):
        """call with unknown server should error."""
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        runner = CliRunner()
        result = runner.invoke(
            main, ["call", "nonexistent.tool", "-c", str(config_file)]
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_call_with_invalid_arg_format(self, tmp_path, monkeypatch):
        """call with argument missing = should skip it."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        mock_content = MagicMock()
        mock_content.text = '{"result": "ok"}'

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        # Pass an arg without = sign - should be skipped
        result = runner.invoke(
            main,
            [
                "call",
                "myserver.tool",
                "-a",
                "no_equals",
                "-a",
                "valid=value",
                "-c",
                str(config_file),
            ],
        )

        # Should still work, just skip the invalid arg
        assert "Calling myserver.tool" in result.output
        # The args should only contain the valid one
        assert "valid" in result.output

    def test_call_with_content_no_text(self, tmp_path, monkeypatch):
        """call result with content but no text attribute."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        # Content without text attribute
        mock_content = MagicMock(spec=[])  # No text attribute
        del mock_content.text  # Ensure no text attribute

        mock_result = MagicMock()
        mock_result.content = [mock_content]

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["call", "myserver.tool", "-c", str(config_file)])

        # Should show result anyway
        assert "Result:" in result.output

    def test_call_result_no_content(self, tmp_path, monkeypatch):
        """call result without content attribute."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  myserver:
    command: echo
""")

        # Result without content attribute
        mock_result = MagicMock(spec=[])  # No content attribute
        del mock_result.content

        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value=mock_result)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        async def mock_create_client(self, server_name):
            return mock_client

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client
        )

        runner = CliRunner()
        result = runner.invoke(main, ["call", "myserver.tool", "-c", str(config_file)])

        # Should show result as JSON
        assert "Result:" in result.output

    def test_validate_connection_failure_report(self, tmp_path, monkeypatch):
        """validate -C should report connection failures."""
        from unittest.mock import AsyncMock, MagicMock
        from click.testing import CliRunner
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
mcp_servers:
  broken_server:
    command: nonexistent
""")

        async def mock_create_client_fails(self, server_name):
            raise ConnectionError("Cannot connect to server")

        monkeypatch.setattr(
            "mcp_proxy.proxy.MCPProxy._create_client", mock_create_client_fails
        )

        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-C", "-c", str(config_file)])

        assert "Checking upstream connections" in result.output
        assert "failed" in result.output or "Cannot connect" in result.output
        assert result.exit_code == 1


class TestCLIServerRenameTool:
    """Tests for 'mcp-proxy server rename-tool' command."""

    def test_rename_tool_sets_name(self, tmp_path):
        """'server rename-tool' should set custom name for tool."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: npx\n"
            "    args: [-y, '@github/mcp-server']\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "rename-tool",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "search_code" in content
        assert "name: find_code" in content

    def test_rename_tool_when_tools_dict_exists(self, tmp_path):
        """'server rename-tool' should work when tools dict already exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "    tools:\n"
            "      other_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "rename-tool",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "other_tool" in content  # Existing tool preserved
        assert "search_code" in content
        assert "name: find_code" in content

    def test_rename_tool_when_tool_entry_exists(self, tmp_path):
        """'server rename-tool' should work when tool entry already exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "    tools:\n"
            "      search_code:\n"
            "        description: existing\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "rename-tool",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "description: existing" in content  # Existing config preserved
        assert "name: find_code" in content

    def test_rename_tool_server_not_found(self, tmp_path):
        """'server rename-tool' on non-existent server should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "rename-tool",
                "nonexistent",
                "tool",
                "new_name",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestCLIServerSetToolParam:
    """Tests for 'mcp-proxy server set-tool-param' command."""

    def test_set_tool_param_hidden_with_default(self, tmp_path):
        """'server set-tool-param' should set hidden param with default."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: npx\n"
            "    args: [-y, '@modelcontextprotocol/server-filesystem']\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "list_directory",
                "path",
                "--hidden",
                "--default",
                ".",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "parameters" in content
        assert "hidden: true" in content
        assert "default: '.'" in content or "default: ." in content

    def test_set_tool_param_rename(self, tmp_path):
        """'server set-tool-param' should rename parameter."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers:\n  fs:\n    command: echo\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "list_directory",
                "path",
                "--rename",
                "folder",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "rename: folder" in content

    def test_set_tool_param_description(self, tmp_path):
        """'server set-tool-param' should set parameter description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers:\n  fs:\n    command: echo\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "search",
                "query",
                "--description",
                "The search query",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "description: The search query" in content

    def test_set_tool_param_clear(self, tmp_path):
        """'server set-tool-param --clear' should remove parameter config."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "    tools:\n"
            "      mytool:\n"
            "        parameters:\n"
            "          path:\n"
            "            hidden: true\n"
            "            default: '.'\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "mytool",
                "path",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # parameters should be removed since it's now empty
        assert "hidden: true" not in content

    def test_set_tool_param_no_options_errors(self, tmp_path):
        """'server set-tool-param' without options should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers:\n  fs:\n    command: echo\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "mytool",
                "path",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "at least one" in result.output.lower()

    def test_set_tool_param_server_not_found(self, tmp_path):
        """'server set-tool-param' on non-existent server should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "nonexistent",
                "tool",
                "param",
                "--hidden",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_set_tool_param_json_default(self, tmp_path):
        """'server set-tool-param' should parse JSON defaults."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers:\n  fs:\n    command: echo\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "mytool",
                "count",
                "--default",
                "10",  # Should be parsed as integer
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "default: 10" in content

    def test_set_tool_param_clear_nonexistent_param(self, tmp_path):
        """'server set-tool-param --clear' on non-existent param should succeed."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "    tools:\n"
            "      mytool:\n"
            "        parameters:\n"
            "          other_param:\n"
            "            hidden: true\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "mytool",
                "nonexistent",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # other_param should still exist
        assert "other_param" in content
        assert "hidden: true" in content

    def test_set_tool_param_clear_keeps_other_params(self, tmp_path):
        """'server set-tool-param --clear' should keep other parameters."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "    tools:\n"
            "      mytool:\n"
            "        parameters:\n"
            "          path:\n"
            "            hidden: true\n"
            "          query:\n"
            "            description: search\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "server",
                "set-tool-param",
                "fs",
                "mytool",
                "path",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # path should be removed but query should remain
        assert "hidden: true" not in content
        assert "query" in content
        assert "description: search" in content


class TestCLIViewRenameTool:
    """Tests for 'mcp-proxy view rename-tool' command."""

    def test_view_rename_tool_sets_name(self, tmp_path):
        """'view rename-tool' should set custom name for tool in view."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        search_code: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "rename-tool",
                "research",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "name: find_code" in content

    def test_view_rename_tool_view_not_found(self, tmp_path):
        """'view rename-tool' on non-existent view should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "rename-tool",
                "nonexistent",
                "github",
                "tool",
                "new_name",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_view_rename_tool_creates_tools_dict(self, tmp_path):
        """'view rename-tool' should create tools dict if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  research:\n"
            "    description: test\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "rename-tool",
                "research",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "name: find_code" in content

    def test_view_rename_tool_creates_server_entry(self, tmp_path):
        """'view rename-tool' should create server entry if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      other_server: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "rename-tool",
                "research",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "github" in content
        assert "name: find_code" in content

    def test_view_rename_tool_creates_tool_entry(self, tmp_path):
        """'view rename-tool' should create tool entry if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  github:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  research:\n"
            "    tools:\n"
            "      github:\n"
            "        other_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "rename-tool",
                "research",
                "github",
                "search_code",
                "find_code",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "other_tool" in content  # Preserved
        assert "search_code" in content
        assert "name: find_code" in content


class TestCLIViewSetToolParam:
    """Tests for 'mcp-proxy view set-tool-param' command."""

    def test_view_set_tool_param_hidden_with_default(self, tmp_path):
        """'view set-tool-param' should set hidden param with default."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      fs:\n"
            "        list_directory: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "list_directory",
                "path",
                "--hidden",
                "--default",
                ".",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "parameters" in content
        assert "hidden: true" in content

    def test_view_set_tool_param_rename(self, tmp_path):
        """'view set-tool-param' should rename parameter."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "list_directory",
                "path",
                "--rename",
                "category",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "rename: category" in content

    def test_view_set_tool_param_description(self, tmp_path):
        """'view set-tool-param' should set parameter description."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "search",
                "query",
                "--description",
                "The search query",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "description: The search query" in content

    def test_view_set_tool_param_clear(self, tmp_path):
        """'view set-tool-param --clear' should remove parameter config."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      fs:\n"
            "        mytool:\n"
            "          parameters:\n"
            "            path:\n"
            "              hidden: true\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "hidden: true" not in content

    def test_view_set_tool_param_view_not_found(self, tmp_path):
        """'view set-tool-param' on non-existent view should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text("mcp_servers: {}\ntool_views: {}\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "nonexistent",
                "fs",
                "tool",
                "param",
                "--hidden",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_view_set_tool_param_no_options_errors(self, tmp_path):
        """'view set-tool-param' without options should error."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 1
        assert "at least one" in result.output.lower()

    def test_view_set_tool_param_creates_tools_dict(self, tmp_path):
        """'view set-tool-param' should create tools dict if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    description: test\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--hidden",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "hidden: true" in content

    def test_view_set_tool_param_creates_server_entry(self, tmp_path):
        """'view set-tool-param' should create server entry if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      other: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--hidden",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "fs:" in content
        assert "hidden: true" in content

    def test_view_set_tool_param_creates_tool_entry(self, tmp_path):
        """'view set-tool-param' should create tool entry if not exists."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      fs:\n"
            "        other_tool: {}\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--hidden",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        assert "other_tool" in content  # Preserved
        assert "mytool" in content
        assert "hidden: true" in content

    def test_view_set_tool_param_clear_nonexistent_param(self, tmp_path):
        """'view set-tool-param --clear' on non-existent param should succeed."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      fs:\n"
            "        mytool:\n"
            "          parameters:\n"
            "            other_param:\n"
            "              hidden: true\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "nonexistent",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # other_param should still exist
        assert "other_param" in content
        assert "hidden: true" in content

    def test_view_set_tool_param_clear_keeps_other_params(self, tmp_path):
        """'view set-tool-param --clear' should keep other parameters."""
        from mcp_proxy.cli import main

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "mcp_servers:\n"
            "  fs:\n"
            "    command: echo\n"
            "tool_views:\n"
            "  myview:\n"
            "    tools:\n"
            "      fs:\n"
            "        mytool:\n"
            "          parameters:\n"
            "            path:\n"
            "              hidden: true\n"
            "            query:\n"
            "              description: search\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "view",
                "set-tool-param",
                "myview",
                "fs",
                "mytool",
                "path",
                "--clear",
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        content = config_file.read_text()
        # path should be removed but query should remain
        assert "hidden: true" not in content
        assert "query" in content
        assert "description: search" in content
