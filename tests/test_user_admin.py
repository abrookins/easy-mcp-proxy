"""Portable MCP administration keeps the browser service's ownership boundary."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

from mcp_proxy.identity import AccessDenied, principal_context
from mcp_proxy.user_admin import APP_URI, bounded, reject_inline_secrets
from mcp_proxy.user_gateway import UserProvider
from tests.test_user_gateway import gateway as gateway_fixture
from tests.test_user_gateway import rpc, user_config

# Re-export the pytest fixture without shadowing its imported name.
gateway = gateway_fixture


async def test_mcp_admin_operations_metadata_and_notification(gateway):
    import httpx

    app, alice, bob = gateway
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app),
            base_url="https://proxy.test",
            headers={"Authorization": "Bearer alice"},
        ) as client:
            tools = (await rpc(client, "/view/admin/mcp", "tools/list"))["result"][
                "tools"
            ]
            status = next(t for t in tools if t["name"] == "proxy_status")
            assert status["_meta"]["ui"]["resourceUri"] == APP_URI
            assert status["annotations"]["readOnlyHint"] is True

            async def call(name, arguments=None):
                result = await rpc(
                    client,
                    "/view/admin/mcp",
                    "tools/call",
                    {"name": name, "arguments": arguments or {}},
                )
                assert not result["result"].get("isError"), result
                return result["result"]["structuredContent"]

            assert (await call("proxy_config"))["revision"] is None
            assert (await call("proxy_status"))[
                "browser_url"
            ] == "https://proxy.test/config"
            assert (await call("proxy_history"))["revisions"] == []
            draft = await call(
                "proxy_preview", {"base": None, "config": user_config("owner")}
            )
            assert (
                await call(
                    "proxy_probe", {"revision": draft["revision"], "server": "same"}
                )
            )["state"] == "connected"
            assert (await call("proxy_apply", {"revision": draft["revision"]}))[
                "state"
            ] == "active"
            rollback = await call(
                "proxy_rollback",
                {"base": draft["revision"], "target": draft["revision"]},
            )
            assert rollback["base"] == draft["revision"]
            resource = await rpc(
                client, "/view/admin/mcp", "resources/read", {"uri": APP_URI}
            )
            assert (
                resource["result"]["contents"][0]["mimeType"]
                == "text/html;profile=mcp-app"
            )
            assert "Your configuration" in resource["result"]["contents"][0]["text"]
            result = await rpc(client, "/mcp", "resources/read", {"uri": APP_URI})
            assert "error" in result
            client.headers["Authorization"] = "Bearer bob"
            result = await rpc(
                client,
                "/view/admin/mcp",
                "tools/call",
                {"name": "proxy_apply", "arguments": {"revision": draft["revision"]}},
            )
            assert result["result"]["isError"]
            app.store.grant(bob.user_id, "app", views=["admin"])
            result = await rpc(client, "/view/admin/mcp", "tools/list")
            assert result["result"]["tools"] == []


async def test_admin_error_redaction_scope_and_bounded_input(gateway, monkeypatch):
    app, alice, bob = gateway
    admin = app.administration
    with principal_context(alice):
        with pytest.raises(ToolError, match="access denied"):
            await admin.execute("config")
    alice = replace(alice, view="admin")
    with principal_context(alice):
        with pytest.raises(ToolError, match="Invalid request"):
            await admin.execute(
                "preview",
                {
                    "base": None,
                    "config": {
                        "mcp_servers": {"x": {"command": "echo", "args": ["private"]}}
                    },
                },
            )
        draft = await admin.execute("preview", {"base": None, "config": {}})
        await admin.execute("apply", {"revision": draft["revision"]})
        with pytest.raises(ToolError, match="Revision conflict"):
            await admin.execute("preview", {"base": None, "config": {}})
        with pytest.raises(ToolError, match="Record unavailable"):
            await admin.execute("apply", {"revision": "unknown"})
        monkeypatch.setattr(
            app.runtime, "probe", AsyncMock(side_effect=OSError("private-token"))
        )
        with pytest.raises(ToolError, match="Operation failed") as error:
            await admin.execute("probe", {"revision": "x", "server": "x"})
        assert "private-token" not in str(error.value)
        provider = UserProvider(app.runtime, admin)
        assert await provider.get_tool("not-an-admin-tool") is None
    with pytest.raises(ValueError, match="too large"):
        bounded({"value": "x" * 65536})
    reject_inline_secrets({"env": {"EXISTING": {"$secret": "opaque"}}, "empty": [None]})
    with principal_context(bob), pytest.raises(AccessDenied):
        admin.html()
    await app.runtime.close()
