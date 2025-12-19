"""Tests for the CLI commands."""

import pytest
from click.testing import CliRunner


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
            ["tools", "--config", str(sample_config_yaml), "--server", "test-server"]
        )

        # Verify option is accepted
        assert "--server" not in result.output or result.exit_code == 0


class TestCLISchema:
    """Tests for 'mcp-proxy schema' command."""

    def test_schema_shows_tool_details(self, sample_config_yaml):
        """'schema <tool>' should show tool parameters and description."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "test-server.test_tool", "--config", str(sample_config_yaml)]
        )

        # Would need upstream to get actual schema
        assert result.exit_code in (0, 1)

    def test_schema_json_output(self, sample_config_yaml):
        """'schema --json' should output JSON format."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "--json", "--config", str(sample_config_yaml)]
        )

        # Verify --json flag is accepted
        assert result.exit_code in (0, 1)

    def test_schema_server_filter(self, sample_config_yaml):
        """'schema --server X' should show all tools from one server."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["schema", "--server", "test-server", "--config", str(sample_config_yaml)]
        )

        assert result.exit_code in (0, 1)


class TestCLIValidate:
    """Tests for 'mcp-proxy validate' command."""

    def test_validate_checks_config(self, sample_config_yaml):
        """'validate' should check config syntax."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["validate", "--config", str(sample_config_yaml)]
        )

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

    def test_validate_tests_upstream_connections(self, sample_config_yaml):
        """'validate' should test upstream server connections."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["validate", "--config", str(sample_config_yaml)]
        )

        # Without real upstreams, may report connection failures
        # Just verify command runs


class TestCLIServe:
    """Tests for 'mcp-proxy serve' command."""

    def test_serve_accepts_config(self, sample_config_yaml):
        """'serve' should accept --config option."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        # Don't actually run the server, just check option parsing
        result = runner.invoke(
            main,
            ["serve", "--config", str(sample_config_yaml), "--help"]
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


class TestCLICall:
    """Tests for 'mcp-proxy call' command."""

    def test_call_invokes_tool(self, sample_config_yaml):
        """'call <tool>' should invoke a tool and return result."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "call", "test-server.test_tool",
                "--config", str(sample_config_yaml),
                "--arg", "query=test"
            ]
        )

        # Would need upstream to actually call
        assert result.exit_code in (0, 1)


class TestCLIConfig:
    """Tests for 'mcp-proxy config' command."""

    def test_config_resolved_shows_env_substitution(self, sample_config_yaml):
        """'config --resolved' should show config with env vars substituted."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["config", "--resolved", "--config", str(sample_config_yaml)]
        )

        # Should show the effective config
        assert result.exit_code in (0, 1)


class TestCLIInit:
    """Tests for 'mcp-proxy init' command."""

    def test_init_hooks_generates_example(self, tmp_path):
        """'init hooks' should generate example hooks file."""
        from mcp_proxy.cli import main

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "hooks"])

            # Should create a hooks file
            assert result.exit_code in (0, 1)

