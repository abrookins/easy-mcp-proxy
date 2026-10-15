"""Loopback-only browser acceptance fixture. Never used by production serving."""

import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path

import uvicorn
from fastmcp import Client, FastMCP
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from mcp_proxy.identity import Identity, principal_context
from mcp_proxy.user_gateway import COOKIE, UserGateway
from mcp_proxy.user_runtime import UserRuntime
from mcp_proxy.user_store import UserStore
from tests.test_user_gateway import FakeOAuth

BASE = "http://127.0.0.1:8769"
directory = tempfile.TemporaryDirectory(prefix="proxy-ui-test-")
store = UserStore(Path(directory.name) / "state")
principals = {}
for subject in ("alice", "bob"):
    uid = store.provision("issuer", subject, operator=True)
    store.grant(uid, "app", admin=True, views=["*"])
    principals[subject] = store.resolve(Identity("issuer", subject, "app"))


def factory(config):
    server = FastMCP(config.command)

    @server.tool
    async def echo(value: str):
        return f"{config.command}:{value}"

    @server.tool
    async def hold():
        await asyncio.sleep(3)
        return f"{config.command}:completed"

    return Client(server)


gateway = UserGateway(
    UserRuntime(store, base_url=BASE, client_factory=factory), FakeOAuth()
)


async def login(request):
    principal = principals[request.path_params["subject"]]
    session = store.create_session(principal)
    response = RedirectResponse("/config")
    response.set_cookie(
        COOKIE, gateway.cipher.encrypt(session.encode()).decode(), httponly=True
    )
    return response


async def embedded(request):
    principal = await gateway.principal(request, browser=True)
    with principal_context(replace(principal, view="admin")):
        return HTMLResponse(gateway.administration.html())


async def host(request):
    principal = await gateway.principal(request, browser=True)
    # This fixture proxies the standard host bridge to the real MCP endpoint.
    token = json.dumps(principal.identity.subject)
    return HTMLResponse(
        (Path(__file__).parent / "ui/host.html").read_text().replace("TOKEN", token)
    )


gateway.app.router.routes[0:0] = [
    Route("/test/login/{subject}", login),
    Route("/test/embedded", embedded),
    Route("/test/host", host),
]

if __name__ == "__main__":
    uvicorn.run(gateway.app, host="127.0.0.1", port=8769, access_log=False)
