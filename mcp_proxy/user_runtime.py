"""User-owned runtime generations with independently drained upstream workers."""

import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from mcp_proxy.identity import Principal
from mcp_proxy.managed_config import materialize_config, validate_managed_config
from mcp_proxy.models import ProxyConfig, ToolViewConfig, UpstreamServerConfig
from mcp_proxy.proxy import MCPProxy
from mcp_proxy.state import persistent_key
from mcp_proxy.user_store import Conflict, NotFound, UserStore


class OwnedProxy(MCPProxy):
    """Instruction discovery obeys the same view boundary as tool discovery."""

    def _combined_registry_instructions(self, registry, entity_name, exposure_mode):
        allowed = {tool.server for tool in registry.tools}
        guidance = "\n\n".join(
            value
            for name, value in self.upstream_instructions.items()
            if name in allowed
        )
        return (
            registry.instructions(entity_name, exposure_mode)
            + "\n## Upstream workflow guidance (non-authoritative)\n\n"
            + (guidance or "No upstream workflow guidance is currently available.")
            + "\n"
        )


def upstream_client(config: UpstreamServerConfig) -> Client:
    """Use resolved credentials only; never expand the host environment here."""
    if config.url:
        return Client(StreamableHttpTransport(config.url, headers=config.headers))
    return Client(
        StdioTransport(
            command=config.command,
            args=config.args,
            env=config.env,
            cwd=config.cwd,
            keep_alive=False,
        )
    )


class Connection:
    """One task enters and exits the client, including its cancellation scopes."""

    def __init__(self, client, timeout: float):
        self.client = client
        self.timeout = timeout
        self.refs = 0
        self.ready = asyncio.get_running_loop().create_future()
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self._run())
        self.tools = []

    async def _run(self):
        try:
            async with self.client:
                self.tools = await self.client.list_tools()
                self.ready.set_result(None)
                await self.stop.wait()
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            raise

    async def start(self):
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), self.timeout)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        self.stop.set()
        if not self.ready.done():
            self.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self.task), self.timeout)
        except BaseException:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        # Consume initialization exceptions even when the caller timed out.
        if self.ready.done() and not self.ready.cancelled():
            self.ready.exception()


@dataclass
class Generation:
    user_id: str
    revision: str | None
    proxy: MCPProxy
    mcps: dict[str, FastMCP]
    connections: dict[str, Connection]
    in_flight: int = 0
    retired: bool = False
    idle: asyncio.Event = field(default_factory=asyncio.Event)


class UserRuntime:
    def __init__(
        self,
        store: UserStore,
        *,
        client_factory=upstream_client,
        timeout: float = 10,
        base_url: str = "http://localhost:8000",
    ):
        self.store = store
        self.client_factory = client_factory
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.active: dict[str, Generation] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.retiring: set[asyncio.Task] = set()
        self.draining: dict[str, Generation] = {}
        self._cache_key = persistent_key(store.directory, "config")

    def lock(self, user: str) -> asyncio.Lock:
        return self.locks.setdefault(user, asyncio.Lock())

    def cache_key(self, user: str, view: str = "default") -> str:
        return hmac.new(
            self._cache_key, f"cache:{user}:{view}".encode(), hashlib.sha256
        ).hexdigest()

    async def _build(self, principal, revision, raw, old=None) -> Generation:
        config = ProxyConfig.model_validate(
            materialize_config(self.store, principal, raw)
        )
        config.cache_secret = self.cache_key(principal.user_id)
        config.cache_base_url = self.base_url
        # Default fallback aggregates only this user's servers.
        config.tool_views.setdefault("default", ToolViewConfig(include_all=True))
        connections = {}
        try:
            for name, server in config.mcp_servers.items():
                connection = None
                if (
                    old
                    and name in old.connections
                    and old.connections[name].client.is_connected()
                ):
                    before = old.proxy.config.mcp_servers[name]
                    excluded = {"tools", "cache_outputs"}
                    if before.model_dump(exclude=excluded) == server.model_dump(
                        exclude=excluded
                    ):
                        connection = old.connections[name]
                if connection is None:
                    connection = Connection(self.client_factory(server), self.timeout)
                    await connection.start()
                connection.refs += 1
                connections[name] = connection
            proxy = OwnedProxy(config)
            clients = {name: conn.client for name, conn in connections.items()}
            proxy.upstream_clients = clients
            proxy._active_clients = clients
            proxy._upstream_tools = {
                name: conn.tools for name, conn in connections.items()
            }
            for name, server in config.mcp_servers.items():
                available = {tool.name for tool in connections[name].tools}
                if any(
                    t.enabled and n not in available
                    for n, t in (server.tools or {}).items()
                ):
                    raise ValueError("Configured upstream tool was not discovered")
            for view in config.tool_views.values():
                if not view.include_all:
                    for name, tools in view.tools.items():
                        available = {tool.name for tool in connections[name].tools}
                        if any(
                            t.enabled and n not in available for n, t in tools.items()
                        ):
                            raise ValueError("Configured view tool was not discovered")
            for name, client in clients.items():
                await proxy.fetch_upstream_instructions(name, client)
            mcps = {}
            for name, view in proxy.views.items():
                proxy._cache_secret = self.cache_key(principal.user_id, name)
                proxy.config.cache_base_url = f"{self.base_url}/view/{name}"
                context = proxy._create_cache_context()
                await view.initialize(
                    clients,
                    get_client=proxy.get_active_client,
                    cache_context=context,
                )
                names = [tool.name for tool in proxy.get_view_tools(name)]
                if len(names) != len(set(names)):
                    raise ValueError("Duplicate exposed tool name")
                mcps[name] = proxy.get_view_mcp(name)
            proxy._cache_secret = self.cache_key(principal.user_id, "search")
            proxy.config.cache_base_url = f"{self.base_url}/view/search"
            context = proxy._create_cache_context()
            search = FastMCP("User tool search")
            proxy._initialize_search_view(search, context)
            # Legacy reconnection replaces the client's owning task and is not
            # safe for leased generations. Recovery uses a newly prepared worker.
            proxy.views["_search"]._reconnect_client = None
            proxy._register_instructions_tool(
                search,
                proxy.views["_search"].get_tool_registry("_search"),
                "_search",
                "search_per_server",
            )
            mcps["search"] = search
            if proxy._is_cache_enabled():
                proxy._register_cache_retrieval_tool(search)
            return Generation(principal.user_id, revision, proxy, mcps, connections)
        except BaseException:
            await self._release(connections)
            raise

    async def _release(self, connections):
        for connection in connections.values():
            connection.refs -= 1
            if connection.refs == 0:
                await connection.close()

    async def get(self, principal: Principal) -> Generation:
        self.store.authorize(principal)
        # Revoked references invalidate subsequent calls, including cached runtimes.
        _, sealed = self.store.active(principal)
        materialize_config(self.store, principal, sealed)
        async with self.lock(principal.user_id):
            if principal.user_id not in self.active:
                revision, config = self.store.active(principal)
                self.active[principal.user_id] = await self._build(
                    principal, revision, config
                )
            generation = self.active[principal.user_id]
        if principal.view not in generation.mcps:
            raise NotFound("View not found")
        return generation

    @asynccontextmanager
    async def lease(self, principal: Principal, revision: str | None = None):
        generation = await self.get(principal)
        self.store.authorize(principal)
        if revision is not None and generation.revision != revision:
            raise Conflict("Tools changed; refresh tool discovery")
        generation.in_flight += 1
        generation.idle.clear()
        try:
            yield generation
        finally:
            generation.in_flight -= 1
            if generation.in_flight == 0:
                generation.idle.set()

    async def apply(self, principal: Principal, revision: str) -> dict:
        self.store.authorize(principal, admin=True)
        async with self.lock(principal.user_id):
            row = self.store.revision(principal, revision)
            if row["state"] == "active":
                current, _ = self.store.active(principal)
                return {
                    "revision": revision,
                    "state": "active" if current == revision else "superseded",
                }
            _, previous = self.store.active(principal)
            validate_managed_config(self.store, principal, row["config"], previous)
            self.store.transition(principal, revision, "preparing")
            generation = None
            try:
                old = self.active.get(principal.user_id)
                generation = await self._build(principal, revision, row["config"], old)
                self.store.transition(principal, revision, "active")
                self.active[principal.user_id] = generation
            except BaseException:
                if generation:
                    await self._release(generation.connections)
                self.store.transition(principal, revision, "failed")
                raise
            if old:
                old.retired = True
                self.draining[old.user_id + str(old.revision)] = old
                task = asyncio.create_task(self._retire(old))
                self.retiring.add(task)
                task.add_done_callback(self.retiring.discard)
        return {"revision": revision, "state": "active"}

    async def _retire(self, generation: Generation):
        # Existing calls may finish; timeout bounds retention of retired clients.
        if generation.in_flight:
            try:
                await asyncio.wait_for(generation.idle.wait(), self.timeout)
            except TimeoutError:
                pass
        await self._release(generation.connections)
        self.draining.pop(generation.user_id + str(generation.revision), None)

    async def probe(self, principal: Principal, revision: str, server: str) -> dict:
        self.store.authorize(principal, admin=True)
        row = self.store.revision(principal, revision)
        _, previous = self.store.active(principal)
        config = validate_managed_config(self.store, principal, row["config"], previous)
        if server not in config.mcp_servers:
            raise NotFound("Upstream not found")
        connection = Connection(
            self.client_factory(config.mcp_servers[server]), self.timeout
        )
        try:
            await connection.start()
            return {
                "server": server,
                "state": "connected",
                "tool_count": len(connection.tools),
            }
        finally:
            await connection.close()

    async def close(self):
        for generation in self.active.values():
            await self._retire(generation)
        self.active.clear()
        await asyncio.gather(*self.retiring)

    def status(self, principal: Principal) -> dict[str, Any]:
        self.store.authorize(principal, admin=True)
        revision, _ = self.store.active(principal)
        generation = self.active.get(principal.user_id)
        return {
            "identity": {
                "issuer": principal.identity.issuer,
                "subject": principal.identity.subject,
                "client": principal.identity.client_id,
            },
            "desired_revision": revision,
            "runtime_revision": generation.revision if generation else None,
            "upstreams": sorted(generation.connections) if generation else [],
            "in_flight": generation.in_flight if generation else 0,
            "draining_calls": sum(
                g.in_flight
                for g in self.draining.values()
                if g.user_id == principal.user_id
            ),
            "discovery_refresh": "Refresh the connector tool list after applying",
            "transport": "stateless HTTP; authenticate each request",
            "events": self.store.diagnostics(principal),
        }
