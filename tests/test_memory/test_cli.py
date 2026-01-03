"""Tests for mcp_memory CLI."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from mcp_memory.cli import build_index, init, load_config, main, serve
from mcp_memory.models import MemoryConfig


class TestLoadConfig:
    """Tests for the load_config function."""

    def test_load_config_default_no_config_file(self, tmp_path):
        """Test loading config when no config file exists."""
        config = load_config(str(tmp_path))
        assert isinstance(config, MemoryConfig)
        assert config.base_path == str(tmp_path)

    def test_load_config_explicit_config_file(self, tmp_path):
        """Test loading config from explicit config file."""
        config_file = tmp_path / "custom-config.yaml"
        config_file.write_text(
            yaml.dump({"threads_dir": "custom_threads", "concepts_dir": "custom_concepts"})
        )

        config = load_config(str(tmp_path), config_file=str(config_file))
        assert config.threads_dir == "custom_threads"
        assert config.concepts_dir == "custom_concepts"
        assert config.base_path == str(tmp_path)

    def test_load_config_auto_detect_mcp_memory_yaml(self, tmp_path):
        """Test auto-detecting .mcp-memory.yaml config file."""
        config_file = tmp_path / ".mcp-memory.yaml"
        config_file.write_text(yaml.dump({"threads_dir": "my_threads"}))

        config = load_config(str(tmp_path))
        assert config.threads_dir == "my_threads"

    def test_load_config_auto_detect_mcp_memory_yml(self, tmp_path):
        """Test auto-detecting .mcp-memory.yml config file."""
        config_file = tmp_path / ".mcp-memory.yml"
        config_file.write_text(yaml.dump({"concepts_dir": "my_concepts"}))

        config = load_config(str(tmp_path))
        assert config.concepts_dir == "my_concepts"

    def test_load_config_auto_detect_mcp_memory_yaml_no_dot(self, tmp_path):
        """Test auto-detecting mcp-memory.yaml config file (no dot prefix)."""
        config_file = tmp_path / "mcp-memory.yaml"
        config_file.write_text(yaml.dump({"skills_dir": "my_skills"}))

        config = load_config(str(tmp_path))
        assert config.skills_dir == "my_skills"

    def test_load_config_with_base_path_in_config(self, tmp_path):
        """Test that config file with base_path uses that value."""
        config_file = tmp_path / ".mcp-memory.yaml"
        config_file.write_text(yaml.dump({"base_path": "/custom/path"}))

        config = load_config(str(tmp_path))
        assert config.base_path == "/custom/path"

    def test_load_config_empty_yaml(self, tmp_path):
        """Test loading config from empty YAML file."""
        config_file = tmp_path / ".mcp-memory.yaml"
        config_file.write_text("")

        config = load_config(str(tmp_path))
        assert config.base_path == str(tmp_path)


class TestInitCommand:
    """Tests for the init command."""

    def test_init_creates_directories(self, tmp_path):
        """Test that init creates all expected directories."""
        runner = CliRunner()
        result = runner.invoke(init, ["--path", str(tmp_path)])

        assert result.exit_code == 0
        assert "Memory directory initialized!" in result.output

        # Verify directories were created
        expected_dirs = ["Threads", "Concepts", "Projects", "Skills", "Reflections"]
        for dir_name in expected_dirs:
            assert (tmp_path / dir_name).exists()

    def test_init_default_path(self):
        """Test init uses current directory by default."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(init)
            assert result.exit_code == 0
            assert Path("Threads").exists()


class TestBuildIndexCommand:
    """Tests for the build_index command."""

    def test_build_index_empty(self, tmp_path):
        """Test building index on empty directory."""
        runner = CliRunner()
        # First init the directory
        runner.invoke(init, ["--path", str(tmp_path)])

        result = runner.invoke(build_index, ["--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Building search index" in result.output
        assert "Index built with 0 items" in result.output

    def test_build_index_with_content(self, tmp_path):
        """Test building index with existing content."""
        from mcp_memory.models import Concept
        from mcp_memory.storage import MemoryStorage

        config = MemoryConfig(base_path=str(tmp_path))
        storage = MemoryStorage(config)

        # Create some content
        concept = Concept(name="Test Concept", text="Test content")
        storage.save(concept)

        runner = CliRunner()
        result = runner.invoke(build_index, ["--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Index built with 1 items" in result.output


class TestServeCommand:
    """Tests for the serve command."""

    @patch("mcp_memory.server.create_memory_server")
    def test_serve_stdio_transport(self, mock_create_server, tmp_path):
        """Test serve command with stdio transport."""
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        runner = CliRunner()
        result = runner.invoke(serve, ["--path", str(tmp_path), "--transport", "stdio"])

        assert result.exit_code == 0
        mock_create_server.assert_called_once()
        mock_server.run.assert_called_once_with(transport="stdio")

    @patch("mcp_memory.server.create_memory_server")
    def test_serve_http_transport(self, mock_create_server, tmp_path):
        """Test serve command with http transport."""
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        runner = CliRunner()
        result = runner.invoke(
            serve, ["--path", str(tmp_path), "--transport", "http", "--port", "9000"]
        )

        assert result.exit_code == 0
        mock_server.run.assert_called_once_with(transport="sse", port=9000)

    @patch("mcp_memory.server.create_memory_server")
    def test_serve_with_config_file(self, mock_create_server, tmp_path):
        """Test serve command with explicit config file."""
        mock_server = MagicMock()
        mock_create_server.return_value = mock_server

        config_file = tmp_path / "my-config.yaml"
        config_file.write_text(yaml.dump({"threads_dir": "custom_threads"}))

        runner = CliRunner()
        result = runner.invoke(
            serve, ["--path", str(tmp_path), "--config", str(config_file)]
        )

        assert result.exit_code == 0
        # Verify config was loaded with custom settings
        call_args = mock_create_server.call_args
        assert call_args.kwargs["config"].threads_dir == "custom_threads"

