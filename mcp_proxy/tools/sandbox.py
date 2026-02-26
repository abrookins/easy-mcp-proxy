"""Docker-based code execution sandbox tool.

Executes code in isolated Docker containers with configurable security levels.
Works on Mac (via Docker Desktop/OrbStack) and Linux.

Security Notes:
- Only allowlisted Docker images can be used
- Directory mounts are restricted to configured allowed paths
- Resource limits are capped to prevent DoS
- Package names are validated to prevent command injection
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp_proxy.custom_tools import custom_tool

# Fast-starting base images per language (Alpine-based for speed)
DEFAULT_IMAGES = {
    "python": "python:3.12-alpine",
    "node": "node:22-alpine",
    "bash": "alpine:latest",
}

# Allowlisted images that can be used (in addition to DEFAULT_IMAGES values)
# Add more trusted images here as needed
ALLOWED_IMAGES = {
    "python:3.12-alpine",
    "python:3.11-alpine",
    "python:3.12-slim",
    "node:22-alpine",
    "node:20-alpine",
    "alpine:latest",
    "ubuntu:22.04",
}

# Track active sandbox sessions {session_id: container_id}
_active_sessions: dict[str, str] = {}

# Maximum resource limits
MAX_MEMORY_MB = 1024  # 1GB max
MAX_CPU = 2.0
MAX_TIMEOUT_SECONDS = 300  # 5 minutes max
MAX_ACTIVE_SESSIONS = 10

# Allowed base paths for mounting (empty = no mounting allowed)
# Configure this to your trusted paths, e.g., {"/home/user/sandbox-data"}
ALLOWED_MOUNT_PATHS: set[str] = set()

# Valid package name pattern (alphanumeric, hyphens, underscores, brackets for extras)
# Prevents command injection via package names
PACKAGE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\[\],.<>=]+$")


def _validate_image(image: str | None, language: str) -> tuple[bool, str]:
    """Validate that the image is in the allowlist."""
    if image is None:
        return True, DEFAULT_IMAGES.get(language, DEFAULT_IMAGES["python"])

    # Check against allowlist
    all_allowed = ALLOWED_IMAGES | set(DEFAULT_IMAGES.values())
    if image in all_allowed:
        return True, image

    return (
        False,
        f"Image '{image}' is not in the allowlist. Allowed: {sorted(all_allowed)}",
    )


def _validate_packages(packages: list | None) -> tuple[bool, str]:
    """Validate package names to prevent command injection."""
    if not packages:
        return True, ""

    invalid = []
    for pkg in packages:
        if not isinstance(pkg, str) or not PACKAGE_NAME_PATTERN.match(pkg):
            invalid.append(pkg)

    if invalid:
        return False, f"Invalid package names (possible injection): {invalid}"

    return True, ""


def _validate_mount_path(path: str | None, path_type: str) -> tuple[bool, str]:
    """Validate that a path is within allowed mount directories."""
    if path is None:
        return True, ""

    if not ALLOWED_MOUNT_PATHS:
        return (
            False,
            f"{path_type} mounting is disabled. "
            "Configure ALLOWED_MOUNT_PATHS to enable.",
        )

    resolved = Path(path).resolve()

    for allowed in ALLOWED_MOUNT_PATHS:
        allowed_path = Path(allowed).resolve()
        try:
            resolved.relative_to(allowed_path)
            return True, ""
        except ValueError:
            continue

    return (
        False,
        f"{path_type} path '{path}' is not under allowed paths: {ALLOWED_MOUNT_PATHS}",
    )


def _parse_memory_limit(memory_limit: str) -> tuple[bool, int]:
    """Parse and validate memory limit, return MB value."""
    memory_limit = memory_limit.lower().strip()

    match = re.match(r"^(\d+)(m|mb|g|gb)?$", memory_limit)
    if not match:
        return False, 0

    value = int(match.group(1))
    unit = match.group(2) or "m"

    if unit in ("g", "gb"):
        value *= 1024

    return True, value


def _validate_resource_limits(
    memory_limit: str, cpu_limit: float, timeout: int
) -> tuple[bool, str, str, float, int]:
    """Validate and cap resource limits."""
    # Parse and cap memory
    valid, memory_mb = _parse_memory_limit(memory_limit)
    if not valid:
        return False, f"Invalid memory limit format: {memory_limit}", "", 0.0, 0

    capped_memory = min(memory_mb, MAX_MEMORY_MB)
    memory_str = f"{capped_memory}m"

    # Cap CPU
    capped_cpu = min(max(0.1, cpu_limit), MAX_CPU)

    # Cap timeout
    capped_timeout = min(max(1, timeout), MAX_TIMEOUT_SECONDS)

    return True, "", memory_str, capped_cpu, capped_timeout


# Security configurations per isolation level
ISOLATION_CONFIGS = {
    "minimal": {
        # Fast startup, basic container isolation
        "network": True,
        "read_only": False,
        "no_new_privileges": False,
        "cap_drop_all": False,
    },
    "standard": {
        # Balanced security - no network, read-only filesystem
        "network": False,
        "read_only": True,
        "no_new_privileges": True,
        "cap_drop_all": False,
    },
    "secure": {
        # Maximum Docker security - all hardening options
        "network": False,
        "read_only": True,
        "no_new_privileges": True,
        "cap_drop_all": True,
    },
}


def _build_docker_command(
    code: str,
    language: str,
    image: str | None,
    isolation_level: str,
    timeout: int,
    memory_limit: str,
    cpu_limit: float,
    workdir: Path,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    packages: list[str] | None = None,
) -> list[str]:
    """Build the docker run command with appropriate security settings."""
    config = ISOLATION_CONFIGS.get(isolation_level, ISOLATION_CONFIGS["standard"])
    actual_image = image or DEFAULT_IMAGES.get(language, DEFAULT_IMAGES["python"])

    cmd = ["docker", "run", "--rm"]

    # Resource limits
    cmd.extend(["--memory", memory_limit])
    cmd.extend(["--cpus", str(cpu_limit)])

    # Network isolation - but allow network if installing packages
    if not config["network"] and not packages:
        cmd.append("--network=none")

    # Filesystem security
    if config["read_only"] and not output_dir and not packages:
        cmd.append("--read-only")
        # Need a writable /tmp for some operations
        cmd.extend(["--tmpfs", "/tmp:size=64m"])

    # Privilege restrictions
    if config["no_new_privileges"]:
        cmd.extend(["--security-opt", "no-new-privileges"])

    if config["cap_drop_all"]:
        cmd.extend(["--cap-drop", "ALL"])

    # Mount the code file
    code_file = workdir / "code"
    cmd.extend(["-v", f"{code_file}:/code:ro"])

    # Mount input directory (read-only)
    if input_dir:
        cmd.extend(["-v", f"{input_dir}:/input:ro"])

    # Mount output directory (read-write)
    if output_dir:
        cmd.extend(["-v", f"{output_dir}:/output:rw"])

    # Add the image
    cmd.append(actual_image)

    # Build the execution command
    if packages:
        # Install packages first, then run code
        if language == "python":
            pkg_cmd = f"pip install --quiet {' '.join(packages)} && python /code"
            cmd.extend(["sh", "-c", pkg_cmd])
        elif language == "node":
            pkg_cmd = f"npm install --silent {' '.join(packages)} && node /code"
            cmd.extend(["sh", "-c", pkg_cmd])
        else:
            cmd.extend(["sh", "/code"])
    else:
        # Add the execution command based on language
        if language == "python":
            cmd.extend(["python", "/code"])
        elif language == "node":
            cmd.extend(["node", "/code"])
        elif language == "bash":
            cmd.extend(["sh", "/code"])
        else:
            # Default to running as a script
            cmd.extend(["sh", "/code"])

    return cmd


@custom_tool(
    name="run_code_sandbox",
    description="""Execute code in an isolated Docker container.

Runs code safely in a Docker container with configurable isolation levels:
- minimal: Basic container isolation, network enabled (fastest)
- standard: No network, read-only filesystem (default, balanced)
- secure: All hardening options enabled (most secure)

Supports Python, Node.js, and Bash. Uses Alpine-based images for fast startup.

Features:
- File I/O: Mount input/output directories for file processing
- Packages: Install pip/npm packages before execution
- Custom images: Use any Docker image

Examples:
- Python: run_code_sandbox(code="print('hello')")
- With packages: run_code_sandbox(code="import requests; ...", packages=["requests"])
- File I/O: run_code_sandbox(code="...", input_dir="/data", output_dir="/results")
- Secure: run_code_sandbox(code="...", isolation_level="secure")""",
)
async def run_code_sandbox(
    code: str,
    language: str = "python",
    timeout: int = 30,
    isolation_level: str = "standard",
    memory_limit: str = "256m",
    cpu_limit: float = 1.0,
    image: str | None = None,
    input_dir: str | None = None,
    output_dir: str | None = None,
    packages: list | None = None,
    ctx: Any = None,  # Accepted but not used
) -> dict:
    """Execute code in an isolated Docker container.

    Args:
        code: The code to execute (required)
        language: Programming language - python, node, bash (default: python)
        timeout: Maximum execution time in seconds (default: 30)
        isolation_level: Security level - minimal, standard, secure (default: standard)
        memory_limit: Memory limit, e.g., "256m", "1g" (default: 256m)
        cpu_limit: CPU limit as decimal, e.g., 0.5 for half a core (default: 1.0)
        image: Custom Docker image to use (optional, overrides language default)
        input_dir: Host directory to mount as /input (read-only)
        output_dir: Host directory to mount as /output (read-write)
        packages: List of packages to install (pip for Python, npm for Node)

    Returns:
        Dict with stdout, stderr, return_code, success, and execution metadata
    """
    # Validate inputs
    if language not in DEFAULT_IMAGES and not image:
        return {
            "success": False,
            "error": f"Unsupported language: {language}. Use: {list(DEFAULT_IMAGES)}",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    if isolation_level not in ISOLATION_CONFIGS:
        return {
            "success": False,
            "error": f"Invalid isolation_level: {isolation_level}. "
            f"Use: {list(ISOLATION_CONFIGS)}",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # Check if Docker is available
    if not shutil.which("docker"):
        return {
            "success": False,
            "error": "Docker is not installed or not in PATH",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # SECURITY: Validate image is in allowlist
    valid, image_result = _validate_image(image, language)
    if not valid:
        return {
            "success": False,
            "error": image_result,
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }
    actual_image = image_result

    # SECURITY: Validate packages to prevent command injection
    valid, pkg_error = _validate_packages(packages)
    if not valid:
        return {
            "success": False,
            "error": pkg_error,
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # SECURITY: Validate and cap resource limits
    valid, res_error, memory_limit, cpu_limit, timeout = _validate_resource_limits(
        memory_limit, cpu_limit, timeout
    )
    if not valid:
        return {
            "success": False,
            "error": res_error,
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # SECURITY: Validate mount paths are within allowed directories
    valid, mount_error = _validate_mount_path(input_dir, "input_dir")
    if not valid:
        return {
            "success": False,
            "error": mount_error,
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    valid, mount_error = _validate_mount_path(output_dir, "output_dir")
    if not valid:
        return {
            "success": False,
            "error": mount_error,
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # Validate and convert directory paths
    input_path = Path(input_dir) if input_dir else None
    output_path = Path(output_dir) if output_dir else None

    if input_path and not input_path.exists():
        return {
            "success": False,
            "error": f"Input directory does not exist: {input_dir}",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    # Create output directory if specified but doesn't exist
    if output_path:
        output_path.mkdir(parents=True, exist_ok=True)

    # Create temp directory and write code file
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        code_file = workdir / "code"
        code_file.write_text(code)

        # Build the docker command
        cmd = _build_docker_command(
            code=code,
            language=language,
            image=actual_image,
            isolation_level=isolation_level,
            timeout=timeout,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
            workdir=workdir,
            input_dir=input_path,
            output_dir=output_path,
            packages=packages,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "success": False,
                    "error": f"Execution timed out after {timeout} seconds",
                    "stdout": "",
                    "stderr": "",
                    "return_code": -1,
                    "timed_out": True,
                }

            # List output files if output_dir was used
            output_files = None
            if output_path and output_path.exists():
                output_files = [f.name for f in output_path.iterdir()]

            result = {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
                "return_code": proc.returncode,
                "language": language,
                "isolation_level": isolation_level,
            }

            if output_files is not None:
                result["output_files"] = output_files

            return result

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "return_code": -1,
            }


@custom_tool(
    name="sandbox_session_start",
    description="""Start a persistent sandbox session.

Creates a long-running Docker container that stays alive for multiple commands.
Useful for interactive development, installing packages once, and maintaining state.

Returns a session_id to use with sandbox_session_exec and sandbox_session_stop.

Example:
- Start: session = sandbox_session_start(language="python", packages=["pandas"])
- Execute: sandbox_session_exec(session_id=session["session_id"], code="...")
- Stop: sandbox_session_stop(session_id=session["session_id"])""",
)
async def sandbox_session_start(
    language: str = "python",
    memory_limit: str = "512m",
    cpu_limit: float = 1.0,
    image: str | None = None,
    packages: list | None = None,
    working_dir: str | None = None,
    ctx: Any = None,  # Accepted but not used
) -> dict:
    """Start a persistent sandbox session.

    Args:
        language: Programming language - python, node, bash (default: python)
        memory_limit: Memory limit (default: 512m)
        cpu_limit: CPU limit (default: 1.0)
        image: Custom Docker image (optional)
        packages: Packages to pre-install (optional)
        working_dir: Host directory to mount as /workspace (optional)

    Returns:
        Dict with session_id, container_id, and status
    """
    if not shutil.which("docker"):
        return {"success": False, "error": "Docker is not installed or not in PATH"}

    if language not in DEFAULT_IMAGES and not image:
        return {
            "success": False,
            "error": f"Unsupported language: {language}. Use: {list(DEFAULT_IMAGES)}",
        }

    # SECURITY: Validate image is in allowlist
    valid, image_result = _validate_image(image, language)
    if not valid:
        return {"success": False, "error": image_result}
    actual_image = image_result

    # SECURITY: Validate packages
    valid, pkg_error = _validate_packages(packages)
    if not valid:
        return {"success": False, "error": pkg_error}

    # SECURITY: Validate resource limits
    valid, res_error, memory_limit, cpu_limit, _ = _validate_resource_limits(
        memory_limit,
        cpu_limit,
        30,  # timeout not used for sessions
    )
    if not valid:
        return {"success": False, "error": res_error}

    # SECURITY: Validate working_dir mount path
    valid, mount_error = _validate_mount_path(working_dir, "working_dir")
    if not valid:
        return {"success": False, "error": mount_error}

    # SECURITY: Check session limit
    if len(_active_sessions) >= MAX_ACTIVE_SESSIONS:
        return {
            "success": False,
            "error": f"Maximum active sessions ({MAX_ACTIVE_SESSIONS}) reached. "
            "Stop existing sessions first.",
        }

    session_id = str(uuid.uuid4())[:8]
    container_name = f"sandbox-{session_id}"

    cmd = [
        "docker",
        "run",
        "-d",  # Detached mode
        "--name",
        container_name,
        "--memory",
        memory_limit,
        "--cpus",
        str(cpu_limit),
        # SECURITY: Add hardening even for sessions
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
    ]

    # Mount working directory if provided (already validated above)
    if working_dir:
        work_path = Path(working_dir)
        if not work_path.exists():
            work_path.mkdir(parents=True, exist_ok=True)
        cmd.extend(["-v", f"{work_path.absolute()}:/workspace"])
        cmd.extend(["-w", "/workspace"])

    cmd.append(actual_image)
    cmd.extend(["tail", "-f", "/dev/null"])  # Keep container running

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to start container: {stderr.decode()}",
            }

        container_id = stdout.decode().strip()[:12]
        _active_sessions[session_id] = container_name

        # Install packages if requested (already validated above)
        if packages:
            if language == "python":
                pkg_cmd = ["pip", "install", "--quiet"] + list(packages)
            elif language == "node":
                pkg_cmd = ["npm", "install", "--silent"] + list(packages)
            else:
                pkg_cmd = None

            if pkg_cmd:
                install_proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    container_name,
                    *pkg_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, install_err = await install_proc.communicate()
                if install_proc.returncode != 0:
                    return {
                        "success": False,
                        "error": f"Package install failed: {install_err.decode()}",
                        "session_id": session_id,
                    }

        return {
            "success": True,
            "session_id": session_id,
            "container_id": container_id,
            "container_name": container_name,
            "language": language,
            "packages_installed": packages or [],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@custom_tool(
    name="sandbox_session_exec",
    description="""Execute code in an existing sandbox session.

Runs code in a persistent container created by sandbox_session_start.
State (variables, installed packages, files) persists between executions.

Example:
- sandbox_session_exec(session_id="abc123", code="x = 42")
- sandbox_session_exec(session_id="abc123", code="print(x)")  # prints 42""",
)
async def sandbox_session_exec(
    session_id: str,
    code: str,
    timeout: int = 30,
    ctx: Any = None,  # Accepted but not used
) -> dict:
    """Execute code in an existing sandbox session.

    Args:
        session_id: Session ID from sandbox_session_start
        code: Code to execute
        timeout: Execution timeout in seconds (default: 30)

    Returns:
        Dict with stdout, stderr, return_code, and success
    """
    if session_id not in _active_sessions:
        return {
            "success": False,
            "error": f"Session not found: {session_id}. "
            f"Active sessions: {list(_active_sessions.keys())}",
            "stdout": "",
            "stderr": "",
            "return_code": -1,
        }

    container_name = _active_sessions[session_id]

    # Write code to a temp file and copy to container
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        temp_file = f.name

    try:
        # Copy code file to container
        copy_proc = await asyncio.create_subprocess_exec(
            "docker",
            "cp",
            temp_file,
            f"{container_name}:/tmp/code",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await copy_proc.communicate()

        # Execute the code
        exec_cmd = ["docker", "exec", container_name, "python", "/tmp/code"]
        proc = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Execution timed out after {timeout} seconds",
                "stdout": "",
                "stderr": "",
                "return_code": -1,
                "timed_out": True,
            }

        return {
            "success": proc.returncode == 0,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "return_code": proc.returncode,
            "session_id": session_id,
        }

    finally:
        os.unlink(temp_file)


@custom_tool(
    name="sandbox_session_stop",
    description="""Stop and remove a sandbox session.

Stops the container and cleans up resources. Call this when done with a session.

Example: sandbox_session_stop(session_id="abc123")""",
)
async def sandbox_session_stop(
    session_id: str,
    ctx: Any = None,  # Accepted but not used
) -> dict:
    """Stop and remove a sandbox session.

    Args:
        session_id: Session ID from sandbox_session_start

    Returns:
        Dict with success status
    """
    if session_id not in _active_sessions:
        return {
            "success": False,
            "error": f"Session not found: {session_id}",
        }

    container_name = _active_sessions[session_id]

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        del _active_sessions[session_id]

        return {
            "success": True,
            "message": f"Session {session_id} stopped and removed",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@custom_tool(
    name="sandbox_session_list",
    description="""List all active sandbox sessions.

Returns information about all currently running sandbox sessions.""",
)
async def sandbox_session_list(
    ctx: Any = None,  # Accepted but not used
) -> dict:
    """List all active sandbox sessions.

    Returns:
        Dict with list of active sessions
    """
    sessions = []
    for session_id, container_name in _active_sessions.items():
        # Check if container is still running
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "-f",
            "{{.State.Running}}",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        is_running = stdout.decode().strip() == "true"

        sessions.append(
            {
                "session_id": session_id,
                "container_name": container_name,
                "running": is_running,
            }
        )

    return {"success": True, "sessions": sessions, "count": len(sessions)}
