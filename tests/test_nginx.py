"""Tests for nginx configuration generation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from mcp_proxy.nginx import NginxConfig, generate_nginx_config


class TestNginxConfig:
    """Tests for NginxConfig dataclass."""

    def test_default_values(self):
        """NginxConfig should have sensible defaults."""
        config = NginxConfig(server_name="example.com")
        assert config.server_name == "example.com"
        assert config.backend_port == 8000
        assert config.backend_host == "127.0.0.1"
        assert config.ssl_certificate is None
        assert config.ssl_certificate_key is None
        assert config.health_path == "/mcp/health"
        assert config.proxy_read_timeout == 300
        assert config.proxy_connect_timeout == 60
        assert config.proxy_send_timeout == 300
        assert config.extra_locations == {}

    def test_custom_values(self):
        """NginxConfig should accept custom values."""
        config = NginxConfig(
            server_name="mcp.example.com",
            backend_port=9000,
            backend_host="192.168.1.100",
            ssl_certificate="/custom/cert.pem",
            ssl_certificate_key="/custom/key.pem",
            health_path="/health",
            proxy_read_timeout=600,
            extra_locations={"/api": "http://other-backend:3000"},
        )
        assert config.server_name == "mcp.example.com"
        assert config.backend_port == 9000
        assert config.backend_host == "192.168.1.100"
        assert config.ssl_certificate == "/custom/cert.pem"
        assert config.extra_locations == {"/api": "http://other-backend:3000"}


class TestGenerateNginxConfig:
    """Tests for generate_nginx_config function."""

    def test_basic_config_generation(self):
        """generate_nginx_config should create valid nginx config."""
        config = NginxConfig(server_name="mcp.example.com")
        result = generate_nginx_config(config)

        assert "server_name mcp.example.com" in result
        assert "listen 443 ssl http2" in result
        assert "proxy_pass http://mcp_backend" in result
        assert "server 127.0.0.1:8000" in result

    def test_custom_ssl_paths(self):
        """generate_nginx_config should use custom SSL paths when provided."""
        config = NginxConfig(
            server_name="mcp.example.com",
            ssl_certificate="/etc/ssl/custom.crt",
            ssl_certificate_key="/etc/ssl/custom.key",
        )
        result = generate_nginx_config(config)

        assert "ssl_certificate /etc/ssl/custom.crt" in result
        assert "ssl_certificate_key /etc/ssl/custom.key" in result

    def test_default_ssl_paths(self):
        """generate_nginx_config should use Let's Encrypt paths by default."""
        config = NginxConfig(server_name="mcp.example.com")
        result = generate_nginx_config(config)

        assert "/etc/letsencrypt/live/mcp.example.com/fullchain.pem" in result
        assert "/etc/letsencrypt/live/mcp.example.com/privkey.pem" in result

    def test_authorization_header(self):
        """generate_nginx_config should include Authorization header passthrough."""
        config = NginxConfig(server_name="mcp.example.com")
        result = generate_nginx_config(config)

        assert "proxy_set_header Authorization $http_authorization" in result

    def test_sse_support(self):
        """generate_nginx_config should include SSE support settings."""
        config = NginxConfig(server_name="mcp.example.com")
        result = generate_nginx_config(config)

        assert "proxy_buffering off" in result
        assert "proxy_cache off" in result
        assert "chunked_transfer_encoding off" in result

    def test_health_endpoint(self):
        """generate_nginx_config should include health check location."""
        config = NginxConfig(server_name="mcp.example.com", health_path="/mcp/health")
        result = generate_nginx_config(config)

        assert "location /mcp/health" in result

    def test_http_redirect(self):
        """generate_nginx_config should include HTTP to HTTPS redirect."""
        config = NginxConfig(server_name="mcp.example.com")
        result = generate_nginx_config(config)

        assert "listen 80" in result
        assert "return 301 https://$server_name$request_uri" in result

    def test_custom_timeouts(self):
        """generate_nginx_config should use custom timeout values."""
        config = NginxConfig(
            server_name="mcp.example.com",
            proxy_read_timeout=600,
            proxy_send_timeout=600,
        )
        result = generate_nginx_config(config)

        assert "proxy_read_timeout 600s" in result
        assert "proxy_send_timeout 600s" in result

    def test_extra_locations(self):
        """generate_nginx_config should include extra locations."""
        config = NginxConfig(
            server_name="mcp.example.com",
            extra_locations={"/api/v2": "http://api-server:3000"},
        )
        result = generate_nginx_config(config)

        assert "location /api/v2" in result
        assert "proxy_pass http://api-server:3000" in result

    def test_custom_backend(self):
        """generate_nginx_config should use custom backend host/port."""
        config = NginxConfig(
            server_name="mcp.example.com",
            backend_host="10.0.0.5",
            backend_port=9000,
        )
        result = generate_nginx_config(config)

        assert "server 10.0.0.5:9000" in result


class TestNginxCLI:
    """Tests for nginx CLI commands."""

    def test_nginx_group_help(self):
        """nginx command group should show help."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        result = runner.invoke(nginx, ["--help"])
        assert result.exit_code == 0
        assert "nginx reverse proxy" in result.output.lower()

    def test_nginx_generate_stdout(self):
        """nginx generate should output to stdout by default."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        result = runner.invoke(nginx, ["generate", "mcp.example.com"])
        assert result.exit_code == 0
        assert "server_name mcp.example.com;" in result.output

    def test_nginx_generate_with_options(self):
        """nginx generate should accept custom options."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        result = runner.invoke(
            nginx,
            [
                "generate",
                "mcp.example.com",
                "--port",
                "9000",
                "--host",
                "0.0.0.0",
                "--timeout",
                "600",
            ],
        )
        assert result.exit_code == 0
        assert "server 0.0.0.0:9000;" in result.output
        assert "proxy_read_timeout 600s;" in result.output

    def test_nginx_generate_to_file(self):
        """nginx generate should write to file with --output."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                nginx, ["generate", "mcp.example.com", "--output", "nginx.conf"]
            )
            assert result.exit_code == 0
            assert "written to nginx.conf" in result.output
            content = Path("nginx.conf").read_text()
            assert "server_name mcp.example.com;" in content

    def test_nginx_generate_with_ssl_paths(self):
        """nginx generate should accept custom SSL paths."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        result = runner.invoke(
            nginx,
            [
                "generate",
                "mcp.example.com",
                "--ssl-cert",
                "/custom/cert.pem",
                "--ssl-key",
                "/custom/key.pem",
            ],
        )
        assert result.exit_code == 0
        assert "/custom/cert.pem" in result.output

    def test_nginx_install_directory_not_found(self):
        """nginx install should handle missing directory."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                nginx,
                [
                    "install",
                    "mcp.example.com",
                    "--nginx-dir",
                    "/nonexistent/path",
                    "--no-enable",
                    "--no-reload",
                ],
            )
            assert result.exit_code == 1
            assert "directory not found" in result.output.lower()

    def test_nginx_install_permission_error(self):
        """nginx install should handle permission errors."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            with patch("pathlib.Path.write_text", side_effect=PermissionError):
                result = runner.invoke(
                    nginx,
                    [
                        "install",
                        "mcp.example.com",
                        "--nginx-dir",
                        "sites-available",
                        "--no-enable",
                        "--no-reload",
                    ],
                )
                assert result.exit_code == 1
                assert "permission denied" in result.output.lower()

    def test_nginx_install_success(self):
        """nginx install should write config and enable site."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            result = runner.invoke(
                nginx,
                [
                    "install",
                    "mcp.example.com",
                    "--nginx-dir",
                    "sites-available",
                    "--no-reload",
                ],
            )
            assert result.exit_code == 0
            assert "Configuration written" in result.output
            assert "Site enabled" in result.output
            config_file = Path("sites-available/mcp-proxy-mcp.example.com")
            assert config_file.exists()
            symlink = Path("sites-enabled/mcp-proxy-mcp.example.com")
            assert symlink.is_symlink()

    def test_nginx_install_already_enabled(self):
        """nginx install should handle already enabled site."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            # Pre-create symlink
            config_file = Path("sites-available/mcp-proxy-mcp.example.com")
            config_file.write_text("existing")
            symlink = Path("sites-enabled/mcp-proxy-mcp.example.com")
            symlink.symlink_to(config_file)
            result = runner.invoke(
                nginx,
                [
                    "install",
                    "mcp.example.com",
                    "--nginx-dir",
                    "sites-available",
                    "--no-reload",
                ],
            )
            assert result.exit_code == 0
            assert "already enabled" in result.output

    def test_nginx_install_with_reload_failure(self):
        """nginx install should handle nginx config test failure."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="config error")
                result = runner.invoke(
                    nginx,
                    [
                        "install",
                        "mcp.example.com",
                        "--nginx-dir",
                        "sites-available",
                        "--reload",
                    ],
                )
                assert result.exit_code == 1
                assert "config test failed" in result.output.lower()

    def test_nginx_install_with_reload_success(self):
        """nginx install should reload nginx on success."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(
                    nginx,
                    [
                        "install",
                        "mcp.example.com",
                        "--nginx-dir",
                        "sites-available",
                        "--reload",
                    ],
                )
                assert result.exit_code == 0
                assert "reloaded successfully" in result.output.lower()

    def test_nginx_certbot_dry_run(self):
        """nginx certbot should support dry-run mode."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(
                nginx,
                [
                    "certbot",
                    "mcp.example.com",
                    "--email",
                    "admin@example.com",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0
            assert "--dry-run" in result.output
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "--dry-run" in call_args

    def test_nginx_certbot_success(self):
        """nginx certbot should run certbot command."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(
                nginx,
                ["certbot", "mcp.example.com", "--email", "admin@example.com"],
            )
            assert result.exit_code == 0
            assert "Certificate obtained" in result.output
            mock_run.assert_called_once()

    def test_nginx_certbot_failure(self):
        """nginx certbot should handle certbot failure."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = runner.invoke(
                nginx,
                ["certbot", "mcp.example.com", "--email", "admin@example.com"],
            )
            assert result.exit_code == 1
            assert "Certbot failed" in result.output

    def test_nginx_install_no_enable(self):
        """nginx install should skip enabling when --no-enable is passed."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("sites-available").mkdir()
            Path("sites-enabled").mkdir()
            result = runner.invoke(
                nginx,
                [
                    "install",
                    "mcp.example.com",
                    "--nginx-dir",
                    "sites-available",
                    "--no-enable",
                    "--no-reload",
                ],
            )
            assert result.exit_code == 0
            assert "Configuration written" in result.output
            assert "Site enabled" not in result.output
            symlink = Path("sites-enabled/mcp-proxy-mcp.example.com")
            assert not symlink.exists()

    def test_nginx_self_signed_success(self):
        """nginx self-signed should generate certificate files."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(
                    nginx,
                    ["self-signed", "mcp.example.com", "--output-dir", "."],
                )
                assert result.exit_code == 0
                assert "Generating self-signed certificate" in result.output
                assert "mcp.example.com.crt" in result.output
                assert "mcp.example.com.key" in result.output
                mock_run.assert_called_once()

    def test_nginx_self_signed_failure(self):
        """nginx self-signed should handle openssl failure."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stderr="openssl error")
                result = runner.invoke(
                    nginx,
                    ["self-signed", "mcp.example.com", "--output-dir", "."],
                )
                assert result.exit_code == 1
                assert "OpenSSL failed" in result.output

    def test_nginx_self_signed_with_ip(self):
        """nginx self-signed should handle IP addresses."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(
                    nginx,
                    ["self-signed", "192.168.1.100", "--output-dir", "."],
                )
                assert result.exit_code == 0
                # Verify the command includes IP in subjectAltName
                call_args = mock_run.call_args[0][0]
                assert any("IP:192.168.1.100" in arg for arg in call_args)

    def test_nginx_self_signed_custom_days(self):
        """nginx self-signed should accept custom validity days."""
        from mcp_proxy.cli.nginx import nginx

        runner = CliRunner()
        with runner.isolated_filesystem():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = runner.invoke(
                    nginx,
                    [
                        "self-signed",
                        "mcp.example.com",
                        "--output-dir",
                        ".",
                        "--days",
                        "730",
                    ],
                )
                assert result.exit_code == 0
                call_args = mock_run.call_args[0][0]
                assert "730" in call_args


class TestLooksLikeIp:
    """Tests for _looks_like_ip helper function."""

    def test_valid_ip(self):
        """_looks_like_ip should return True for valid IPs."""
        from mcp_proxy.cli.nginx import _looks_like_ip

        assert _looks_like_ip("192.168.1.1") is True
        assert _looks_like_ip("10.0.0.1") is True
        assert _looks_like_ip("255.255.255.255") is True
        assert _looks_like_ip("0.0.0.0") is True

    def test_invalid_ip(self):
        """_looks_like_ip should return False for non-IPs."""
        from mcp_proxy.cli.nginx import _looks_like_ip

        assert _looks_like_ip("example.com") is False
        assert _looks_like_ip("192.168.1") is False
        assert _looks_like_ip("192.168.1.256") is False
        assert _looks_like_ip("192.168.1.1.1") is False
        assert _looks_like_ip("abc.def.ghi.jkl") is False
