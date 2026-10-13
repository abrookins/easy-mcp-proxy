"""Trusted local stdio transport with an explicit, provisioned OAuth owner."""

import fcntl
import os
from pathlib import Path

from fastmcp import FastMCP

from mcp_proxy.identity import Identity, principal_context
from mcp_proxy.user_gateway import UserProvider
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import UserStore


async def serve_owned_stdio():
    directory = os.environ.get("MCP_PROXY_STATE_DIR")
    issuer = os.environ.get("MCP_PROXY_OWNER_ISSUER")
    subject = os.environ.get("MCP_PROXY_OWNER_SUBJECT")
    if not directory or not issuer or not subject:
        raise ValueError(
            "stdio requires MCP_PROXY_STATE_DIR, MCP_PROXY_OWNER_ISSUER and "
            "MCP_PROXY_OWNER_SUBJECT; provision and grant mcp-proxy-local first"
        )
    store = UserStore(Path(directory))
    runtime = UserRuntime(store)
    try:
        with (store.directory / "runtime.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            principal = store.resolve(Identity(issuer, subject, "mcp-proxy-local"))
            server = FastMCP(
                "User MCP Proxy",
                providers=[UserProvider(runtime)],
                mask_error_details=True,
            )
            with principal_context(principal):
                await server.run_stdio_async()
    finally:
        await runtime.close()
        store.close()
