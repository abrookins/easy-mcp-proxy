"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_config_dict():
    """Sample configuration as a dictionary."""
    return {
        "mcp_servers": {
            "test-server": {
                "command": "echo",
                "args": ["test"],
            }
        },
        "tool_views": {
            "test-view": {
                "description": "Test view",
                "exposure_mode": "direct",
                "tools": {"test-server": {"test_tool": {}}},
            }
        },
    }


@pytest.fixture
def sample_config_yaml(tmp_path, sample_config_dict):
    """Write sample config to a YAML file."""
    import yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(sample_config_dict))
    return config_file


@pytest.fixture
def config_with_tools_dict():
    """Configuration with tools explicitly defined on servers."""
    return {
        "mcp_servers": {
            "github": {
                "url": "https://example.com/mcp",
                "tools": {
                    "search_code": {"description": "Search code"},
                    "search_issues": {"description": "Search issues"},
                },
            },
            "memory": {
                "command": "memory-server",
                "tools": {
                    "store": {"description": "Store data"},
                },
            },
        },
        "tool_views": {
            "research": {
                "description": "Research tools",
                "tools": {
                    "github": {
                        "search_code": {},
                    }
                },
            }
        },
    }


@pytest.fixture
def config_with_tools_yaml(tmp_path, config_with_tools_dict):
    """Write config with tools to a YAML file."""
    import yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config_with_tools_dict))
    return config_file
