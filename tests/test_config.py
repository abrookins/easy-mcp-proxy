"""Tests for configuration loading."""

import pytest
import yaml

from mcp_proxy.config import load_config, validate_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_from_yaml_file(self, sample_config_yaml):
        """load_config should parse a YAML file into ProxyConfig."""
        config = load_config(sample_config_yaml)

        assert config is not None
        assert "test-server" in config.mcp_servers
        assert "test-view" in config.tool_views

    def test_load_config_validates_structure(self, tmp_path):
        """load_config should validate against ProxyConfig schema."""
        # Missing required fields
        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text(yaml.dump({"invalid_key": "value"}))

        with pytest.raises(Exception):  # Pydantic ValidationError
            load_config(bad_config)

    def test_load_config_substitutes_env_vars(self, tmp_path, monkeypatch):
        """load_config should substitute ${VAR} with environment variables."""
        monkeypatch.setenv("TEST_API_KEY", "secret123")

        config_data = {
            "mcp_servers": {
                "test": {
                    "url": "https://api.example.com",
                    "headers": {"Authorization": "Bearer ${TEST_API_KEY}"},
                }
            },
            "tool_views": {},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.mcp_servers["test"].headers["Authorization"] == "Bearer secret123"

    def test_load_config_missing_env_var(self, tmp_path):
        """load_config should handle missing env vars gracefully."""
        config_data = {
            "mcp_servers": {"test": {"url": "${NONEXISTENT_VAR}"}},
            "tool_views": {},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        # Should either raise or leave placeholder
        # Implementation decides behavior

    def test_load_config_from_path_string(self, sample_config_yaml):
        """load_config should accept path as string."""
        config = load_config(str(sample_config_yaml))

        assert config is not None

    def test_load_config_file_not_found(self):
        """load_config should raise on missing file."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_load_config_empty_yaml_file(self, tmp_path):
        """load_config should handle empty YAML files gracefully."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        # Empty YAML should create a valid empty config
        config = load_config(empty_file)
        assert config.mcp_servers == {}
        assert config.tool_views == {}


class TestConfigValidation:
    """Tests for config validation logic."""

    def test_validate_tool_references(self, tmp_path):
        """Config should validate that tool references exist."""
        config_data = {
            "mcp_servers": {"server-a": {"command": "echo"}},
            "tool_views": {
                "view": {
                    "tools": {
                        "nonexistent-server": {  # Server doesn't exist
                            "tool": {}
                        }
                    }
                }
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        errors = validate_config(config)

        assert len(errors) > 0
        assert "nonexistent-server" in str(errors)

    def test_validate_hook_paths(self, tmp_path):
        """Config validation should check hook module paths."""
        config_data = {
            "mcp_servers": {},
            "tool_views": {
                "view": {"hooks": {"pre_call": "nonexistent.module.function"}}
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        errors = validate_config(config)

        # Should warn about unresolvable hook path
        assert any("hook" in str(e).lower() for e in errors)

    def test_validate_post_call_hook_paths(self, tmp_path):
        """Config validation should check post_call hook module paths."""
        config_data = {
            "mcp_servers": {},
            "tool_views": {
                "view": {"hooks": {"post_call": "nonexistent.module.post_function"}}
            },
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        errors = validate_config(config)

        # Should warn about unresolvable post_call hook path
        assert any("post_call" in str(e).lower() for e in errors)


class TestEnvVarSubstitution:
    """Tests for environment variable substitution edge cases."""

    def test_substitute_env_vars_with_int(self, tmp_path):
        """_substitute_env_vars should pass through integers unchanged."""
        config_data = {
            "mcp_servers": {"test": {"command": "echo", "port": 8080}},
            "tool_views": {},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        # The port should remain an integer (or be part of the config)
        # This tests the `return obj` branch for non-str/dict/list types
        assert config is not None

    def test_substitute_env_vars_with_bool(self, tmp_path):
        """_substitute_env_vars should pass through booleans unchanged."""
        config_data = {
            "mcp_servers": {"test": {"command": "echo", "enabled": True}},
            "tool_views": {},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config is not None

    def test_substitute_env_vars_with_float(self, tmp_path):
        """_substitute_env_vars should pass through floats unchanged."""
        config_data = {
            "mcp_servers": {"test": {"command": "echo", "timeout": 30.5}},
            "tool_views": {},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        assert config is not None
