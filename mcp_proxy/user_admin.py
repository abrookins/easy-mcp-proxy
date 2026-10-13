"""Typed MCP administration over the same user-owned management service."""

import json
from pathlib import Path

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ServerNotification, ToolListChangedNotification

from mcp_proxy.identity import AccessDenied, current_principal
from mcp_proxy.managed_config import SECRET, ConfigService, _secret_path
from mcp_proxy.user_store import Conflict, NotFound

APP_URI = "ui://mcp-proxy/admin-v1.html"
READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


def reject_inline_secrets(value, path=()):
    """Credential entry belongs in the authenticated browser, outside model input."""
    if isinstance(value, dict):
        if set(value) == {SECRET}:
            return
        for key, item in value.items():
            reject_inline_secrets(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            reject_inline_secrets(item, path)
    elif value is not None and _secret_path(path):
        raise ValueError("Enter credentials in the browser; preserve opaque references")


def bounded(value):
    if len(json.dumps(value).encode()) > 65536:
        raise ValueError("Configuration is too large for MCP; use the browser or CLI")
    return value


class Administration:
    def __init__(self, runtime):
        self.runtime = runtime
        self.service = ConfigService(runtime.store)
        self.mcp = FastMCP("Configuration administration", mask_error_details=True)

        @self.mcp.tool(name="proxy_config", annotations=READ)
        async def read_config() -> dict:
            """Read your configuration with opaque credential references."""
            return await self.execute("config")

        @self.mcp.tool(
            name="proxy_status", annotations=READ, meta={"ui": {"resourceUri": APP_URI}}
        )
        async def status() -> dict:
            """Inspect your active revision and open the configuration screen.

            If UI is unavailable, use the browser_url in the result.
            """
            value = await self.execute("status")
            value["browser_url"] = runtime.base_url + "/config"
            return value

        @self.mcp.tool(name="proxy_history", annotations=READ)
        async def history() -> dict:
            """Read your retained revision history, without credentials."""
            return await self.execute("history")

        @self.mcp.tool(name="proxy_preview", annotations=WRITE)
        async def preview(base: str | None, config: dict) -> dict:
            """Preview a replacement config against its expected base.

            Preserve $secret references. Enter new credentials in the browser.
            No upstream process or connection is started by this operation.
            """
            return await self.execute("preview", {"base": base, "config": config})

        @self.mcp.tool(
            name="proxy_apply",
            annotations={
                **WRITE,
                "idempotentHint": True,
                "openWorldHint": True,
                "destructiveHint": True,
            },
        )
        async def apply(revision: str, ctx: Context) -> dict:
            """Apply a previously reviewed candidate revision; stale bases fail."""
            value = await self.execute("apply", {"revision": revision})
            await ctx.session.send_notification(
                ServerNotification(ToolListChangedNotification()),
                related_request_id=ctx.request_context.request_id,
            )
            return value

        @self.mcp.tool(name="proxy_probe", annotations={**WRITE, "openWorldHint": True})
        async def probe(revision: str, server: str) -> dict:
            """Connect a candidate upstream temporarily, then close the probe."""
            return await self.execute("probe", {"revision": revision, "server": server})

        @self.mcp.tool(name="proxy_rollback", annotations=WRITE)
        async def rollback(base: str, target: str) -> dict:
            """Preview a retained revision under current permissions and secrets."""
            return await self.execute("rollback", {"base": base, "target": target})

    def principal(self):
        principal = current_principal()
        self.runtime.store.authorize(principal, admin=True)
        if principal.view != "admin":
            raise AccessDenied("Use the explicitly granted administration endpoint")
        return principal

    async def execute(self, action, data=None):
        try:
            principal = self.principal()
            data = data or {}
            bounded(data)
            if action == "config":
                value = self.service.read(principal)
            elif action == "status":
                value = self.runtime.status(principal)
            elif action == "history":
                value = {"revisions": self.runtime.store.history(principal)}
            elif action == "preview":
                reject_inline_secrets(data["config"])
                value = self.service.preview(principal, data["base"], data["config"])
            elif action == "apply":
                value = await self.runtime.apply(principal, data["revision"])
            elif action == "probe":
                value = await self.runtime.probe(
                    principal, data["revision"], data["server"]
                )
            else:
                value = self.service.rollback_preview(
                    principal, data["base"], data["target"]
                )
            return bounded(value)
        except AccessDenied:
            raise ToolError("Administration access denied") from None
        except Conflict:
            raise ToolError("Revision conflict; reload and preview again") from None
        except NotFound:
            raise ToolError("Record unavailable for this account") from None
        except ValueError:
            raise ToolError(
                "Invalid request; use the browser for secrets or large configs"
            ) from None
        except Exception:
            raise ToolError(
                "Operation failed; active configuration is unchanged"
            ) from None

    def html(self):
        self.principal()
        return (Path(__file__).parent / "admin_ui/embedded.html").read_text()
