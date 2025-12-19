"""Tests for configuration loading."""

import pytest


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_from_yaml_file(self, sample_config_yaml):
        """load_config should parse a YAML file into ProxyConfig."""
        from mcp_proxy.config import load_config

        config = load_config(sample_config_yaml)

        assert config is not None
        assert "test-server" in config.mcp_servers
        assert "test-view" in config.tool_views

    def test_load_config_validates_structure(self, tmp_path):
        """load_config should validate against ProxyConfig schema."""
        from mcp_proxy.config import load_config
        import yaml

        # Missing required fields
        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text(yaml.dump({"invalid_key": "value"}))

        with pytest.raises(Exception):  # Pydantic ValidationError
            load_config(bad_config)

    def test_load_config_substitutes_env_vars(self, tmp_path, monkeypatch):
        """load_config should substitute ${VAR} with environment variables."""
        from mcp_proxy.config import load_config
        import yaml

        monkeypatch.setenv("TEST_API_KEY", "secret123")

        config_data = {
            "mcp_servers": {
                "test": {
                    "url": "https://api.example.com",
                    "headers": {
                        "Authorization": "Bearer ${TEST_API_KEY}"
                    }
                }
            },
            "tool_views": {}
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)

        assert config.mcp_servers["test"].headers["Authorization"] == "Bearer secret123"

    def test_load_config_missing_env_var(self, tmp_path):
        """load_config should handle missing env vars gracefully."""
        from mcp_proxy.config import load_config
        import yaml

        config_data = {
            "mcp_servers": {
                "test": {
                    "url": "${NONEXISTENT_VAR}"
                }
            },
            "tool_views": {}
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        # Should either raise or leave placeholder
        # Implementation decides behavior

    def test_load_config_from_path_string(self, sample_config_yaml):
        """load_config should accept path as string."""
        from mcp_proxy.config import load_config

        config = load_config(str(sample_config_yaml))

        assert config is not None

    def test_load_config_file_not_found(self):
        """load_config should raise on missing file."""
        from mcp_proxy.config import load_config

        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")


class TestConfigValidation:
    """Tests for config validation logic."""

    def test_validate_tool_references(self, tmp_path):
        """Config should validate that tool references exist."""
        from mcp_proxy.config import load_config, validate_config
        import yaml

        config_data = {
            "mcp_servers": {
                "server-a": {"command": "echo"}
            },
            "tool_views": {
                "view": {
                    "tools": {
                        "nonexistent-server": {  # Server doesn't exist
                            "tool": {}
                        }
                    }
                }
            }
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        errors = validate_config(config)

        assert len(errors) > 0
        assert "nonexistent-server" in str(errors)

    def test_validate_hook_paths(self, tmp_path):
        """Config validation should check hook module paths."""
        from mcp_proxy.config import load_config, validate_config
        import yaml

        config_data = {
            "mcp_servers": {},
            "tool_views": {
                "view": {
                    "hooks": {
                        "pre_call": "nonexistent.module.function"
                    }
                }
            }
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config = load_config(config_file)
        errors = validate_config(config)

        # Should warn about unresolvable hook path
        assert any("hook" in str(e).lower() for e in errors)

