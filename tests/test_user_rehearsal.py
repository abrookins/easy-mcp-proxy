"""Isolated upgrade/restore rehearsal using a real stdio upstream process."""

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys

import yaml

from mcp_proxy.cli.users import import_configuration
from mcp_proxy.config import load_config
from mcp_proxy.identity import Identity
from mcp_proxy.managed_config import ConfigService
from mcp_proxy.user_runtime import UserRuntime, upstream_client
from mcp_proxy.user_store import UserStore


async def test_import_live_update_restart_restore_and_reverse_migration(tmp_path):
    upstream = tmp_path / "upstream.py"
    upstream.write_text("""import os
from fastmcp import FastMCP
server = FastMCP("migration fixture")
@server.tool
async def process_id() -> int:
    return os.getpid()
if __name__ == "__main__":
    server.run(transport="stdio", show_banner=False)
""")
    config_path = tmp_path / "legacy.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "fixture": {"command": sys.executable, "args": [str(upstream)]}
                },
                "tool_views": {"remote": {"include_all": True}},
            }
        )
    )
    original = hashlib.sha256(config_path.read_bytes()).hexdigest()
    directory = tmp_path / "managed"
    store = UserStore(directory)
    uid = store.provision("issuer", "owner", operator=True)
    store.grant(uid, "mcp-proxy-local", admin=True, views=["*"])
    principal = store.resolve(Identity("issuer", "owner", "mcp-proxy-local"))
    assert (
        import_configuration(directory, "issuer", "owner", config_path)["state"]
        == "valid"
    )
    imported = import_configuration(directory, "issuer", "owner", config_path, False)
    backup = tmp_path / "backup"
    shutil.copytree(directory, backup)
    runtime = UserRuntime(store)
    first = await runtime.get(principal)
    tool = await first.mcps["remote"].get_tool("process_id")
    first_pid = str(await tool.run({}))
    service = ConfigService(store)
    read = service.read(principal)
    read["config"]["tool_views"]["remote"]["description"] = "updated without restart"
    draft = service.preview(principal, read["revision"], read["config"])
    async with runtime.lease(principal):
        await runtime.apply(principal, draft["revision"])
        second = await runtime.get(principal)
        assert second.connections["fixture"] is first.connections["fixture"]
        tool = await second.mcps["remote"].get_tool("process_id")
        assert str(await tool.run({})) == first_pid
    await runtime.close()
    store.close()
    verify = """import asyncio,sys
from pathlib import Path
from mcp_proxy.user_store import UserStore
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.identity import Identity
async def verify():
    store=UserStore(Path(sys.argv[1]))
    principal=store.resolve(Identity("issuer","owner","mcp-proxy-local"))
    runtime=UserRuntime(store)
    generation=await runtime.get(principal)
    assert generation.revision==sys.argv[2]
    assert await generation.mcps["remote"].get_tool("process_id") is not None
    await runtime.close()
    store.close()
asyncio.run(verify())
"""
    restarted = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", verify, str(directory), draft["revision"]],
        capture_output=True,
        text=True,
    )
    assert restarted.returncode == 0, restarted.stderr
    shutil.rmtree(directory)
    shutil.copytree(backup, directory)
    restored = UserStore(directory)
    assert restored.active(principal)[0] == imported["revision"]
    restored.close()
    assert hashlib.sha256(config_path.read_bytes()).hexdigest() == original
    # Reverse migration starts the unchanged effective legacy transport again.
    legacy = load_config(config_path)
    async with upstream_client(legacy.mcp_servers["fixture"]) as client:
        assert [t.name for t in await client.list_tools()] == ["process_id"]
        result = await client.call_tool("process_id", {})
        assert result.content
    assert json.loads(json.dumps(imported))["state"] == "imported"
