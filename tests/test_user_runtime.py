"""Live configuration preserves unchanged clients and pins in-flight calls."""

import asyncio
from dataclasses import replace

import pytest
from fastmcp import Client, FastMCP

from mcp_proxy.identity import AccessDenied, Identity
from mcp_proxy.managed_config import ConfigService
from mcp_proxy.user_runtime import Connection, UserRuntime, upstream_client
from mcp_proxy.user_store import Conflict, NotFound, UserStore


@pytest.fixture
def runtime(tmp_path):
    store = UserStore(tmp_path / "state")
    principals = []
    for subject in ("alice", "bob"):
        uid = store.provision("issuer", subject, operator=True)
        store.grant(uid, "app", admin=True, views=["*"])
        principals.append(store.resolve(Identity("issuer", subject, "app")))
    clients = []

    def factory(config):
        mcp = FastMCP(config.command)

        @mcp.tool
        async def echo(value: str) -> str:
            return f"{config.command}:{value}"

        client = Client(mcp)
        clients.append(client)
        return client

    manager = UserRuntime(store, client_factory=factory, timeout=0.2)
    yield manager, ConfigService(store), *principals, clients
    store.close()


def config(command="first", description="original"):
    return {
        "mcp_servers": {"same": {"command": command}},
        "tool_views": {"default": {"include_all": True, "description": description}},
    }


async def test_live_apply_retains_clients_and_isolates_users(runtime):
    manager, service, alice, bob, clients = runtime
    assert manager.status(alice)["runtime_revision"] is None
    first = service.preview(alice, None, config())["revision"]
    await manager.apply(alice, first)
    original = await manager.get(alice)
    tool = await original.mcps["default"].get_tool("same_echo")
    if tool is None:
        tool = await original.mcps["default"].get_tool("echo")
    assert tool is not None
    result = await tool.run({"value": "hello"})
    assert "first:hello" in str(result)
    second = service.preview(alice, first, config(description="updated"))["revision"]
    async with manager.lease(alice, first):
        await manager.apply(alice, second)
        updated = await manager.get(alice)
        assert updated is not original
        assert updated.connections["same"] is original.connections["same"]
        assert original.connections["same"].refs == 2
        assert len(clients) == 1
        assert manager.status(alice)["runtime_revision"] == second
    await asyncio.gather(*manager.retiring)
    assert updated.connections["same"].refs == 1
    assert await manager.apply(alice, second) == {"revision": second, "state": "active"}
    bob_revision = service.preview(bob, None, config())["revision"]
    await manager.apply(bob, bob_revision)
    bob_generation = await manager.get(bob)
    assert bob_generation.connections["same"] is not updated.connections["same"]
    assert manager.cache_key(alice.user_id) != manager.cache_key(bob.user_id)
    with pytest.raises(NotFound):
        await manager.get(replace(alice, view="missing"))
    with pytest.raises(Conflict):
        async with manager.lease(alice, first):
            pytest.fail("stale call accepted")
    await manager.close()
    assert all(not c.is_connected() for c in clients)


async def test_changed_upstream_drains_and_probes_are_temporary(runtime):
    manager, service, alice, _, clients = runtime
    first = service.preview(alice, None, config())["revision"]
    await manager.apply(alice, first)
    old = await manager.get(alice)
    second = service.preview(alice, first, config("replacement"))["revision"]
    probe = await manager.probe(alice, second, "same")
    assert probe["tool_count"] == 1
    assert not clients[-1].is_connected()
    with pytest.raises(NotFound):
        await manager.probe(alice, second, "absent")
    async with manager.lease(alice):
        await manager.apply(alice, second)
        assert old.connections["same"].client.is_connected()
    await asyncio.gather(*manager.retiring)
    assert not old.connections["same"].client.is_connected()
    assert len(clients) == 3
    await manager.close()


async def test_empty_owner_lazy_runtime_and_revocation(runtime):
    manager, service, alice, _, _ = runtime
    generation = await manager.get(alice)
    assert generation.revision is None
    assert await generation.mcps["default"].get_tool("private_tool") is None
    service.store.revoke(alice.user_id, "app")
    with pytest.raises(AccessDenied):
        await manager.get(alice)
    await manager.close()


class BrokenClient:
    def __init__(self, *, hangs=False):
        self.hangs = hangs
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def list_tools(self):
        if self.hangs:
            await asyncio.Event().wait()
        raise RuntimeError("upstream unavailable")


async def test_preparation_failures_leave_active_revision(runtime):
    manager, service, alice, _, _ = runtime
    first = service.preview(alice, None, config())["revision"]
    await manager.apply(alice, first)
    broken = BrokenClient()
    manager.client_factory = lambda config: broken
    revision = service.preview(alice, first, config("broken"))["revision"]
    with pytest.raises(RuntimeError, match="unavailable"):
        await manager.apply(alice, revision)
    assert service.store.active(alice)[0] == first
    assert service.store.revision(alice, revision)["state"] == "failed"
    assert broken.closed
    await manager.close()


async def test_connection_timeout_cleans_up():
    client = BrokenClient(hangs=True)
    connection = Connection(client, 0.01)
    with pytest.raises(TimeoutError):
        await connection.start()
    assert connection.task.done()
    assert client.closed


def test_transport_factory_uses_explicit_environment():
    from mcp_proxy.models import UpstreamServerConfig

    http = upstream_client(UpstreamServerConfig(url="https://example.org/mcp"))
    assert http.transport.url == "https://example.org/mcp"
    stdio = upstream_client(UpstreamServerConfig(command="echo", env={"KEY": "value"}))
    assert stdio.transport.env == {"KEY": "value"}
    assert stdio.transport.keep_alive is False


@pytest.mark.parametrize("mode", ["direct", "search", "search_per_server"])
async def test_alias_hidden_defaults_composition_and_instruction_scope(runtime, mode):
    manager, service, alice, bob, _ = runtime
    value = {
        "mcp_servers": {"same": {"command": "owner"}, "hidden": {"command": "hidden"}},
        "tool_views": {
            "restricted": {
                "exposure_mode": mode,
                "tools": {
                    "same": {
                        "echo": {
                            "name": "renamed",
                            "parameters": {
                                "value": {"hidden": True, "default": "private-default"}
                            },
                        }
                    }
                },
                "composite_tools": {
                    "both": {
                        "parallel": {
                            "one": {"tool": "same.echo", "args": {"value": "composed"}}
                        }
                    }
                },
            }
        },
    }
    value["tool_views"]["default"] = {}
    revision = service.preview(alice, None, value)["revision"]
    await manager.apply(alice, revision)
    principal = replace(alice, view="restricted")
    generation = await manager.get(principal)
    generation.proxy.upstream_instructions = {
        "same": "allowed guidance",
        "hidden": "hidden guidance",
    }
    registry = generation.proxy.views["restricted"].get_tool_registry("restricted")
    instructions = generation.proxy._combined_registry_instructions(
        registry, "restricted", mode
    )
    assert "allowed guidance" in instructions
    assert "hidden guidance" not in instructions
    assert "private-default" not in str(registry.metadata())
    view = generation.proxy.views["restricted"]
    info = registry.get("renamed")
    result = await view.call_tool("renamed", {}, info)
    assert "owner:private-default" in str(result)
    composed = await view.call_tool("both", {})
    assert "owner:composed" in str(composed)
    bob_generation = await manager.get(replace(bob, view="default"))
    assert await bob_generation.mcps["default"].get_tool("renamed") is None
    await manager.close()


async def test_cancel_prepare_concurrent_writes_cleanup_and_recovery(runtime):
    manager, service, alice, bob, clients = runtime
    first = service.preview(alice, None, config())["revision"]
    await manager.apply(alice, first)
    one = service.preview(alice, first, config(description="one"))["revision"]
    two = service.preview(alice, first, config(description="two"))["revision"]
    results = await asyncio.gather(
        manager.apply(alice, one), manager.apply(alice, two), return_exceptions=True
    )
    assert sum(isinstance(r, Conflict) for r in results) == 1
    active, _ = service.store.active(alice)
    assert (await manager.apply(alice, first))["state"] == "superseded"
    broken = BrokenClient(hangs=True)
    manager.client_factory = lambda config: broken
    draft = service.preview(alice, active, config("slow"))["revision"]
    task = asyncio.create_task(manager.apply(alice, draft))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.store.active(alice)[0] == active
    assert service.store.revision(alice, draft)["state"] == "failed"
    assert broken.closed
    assert manager.status(bob)["runtime_revision"] is None
    await manager.close()


async def test_committed_candidate_cleanup_and_drain_timeout(runtime, monkeypatch):
    manager, service, alice, _, clients = runtime
    first = service.preview(alice, None, config())["revision"]
    await manager.apply(alice, first)
    second = service.preview(alice, first, config("replacement"))["revision"]
    original_transition = service.store.transition

    def fail_commit(principal, revision, state):
        if state == "active":
            raise OSError("disk full")
        return original_transition(principal, revision, state)

    monkeypatch.setattr(service.store, "transition", fail_commit)
    with pytest.raises(OSError):
        await manager.apply(alice, second)
    assert clients[0].is_connected()
    assert not clients[-1].is_connected()
    monkeypatch.setattr(service.store, "transition", original_transition)
    third = service.preview(alice, first, config("replacement"))["revision"]
    async with manager.lease(alice):
        await manager.apply(alice, third)
        assert manager.status(alice)["draining_calls"] == 1
        await asyncio.gather(*manager.retiring)
        assert not clients[0].is_connected()
    await manager.close()


async def test_duplicate_tool_names_fail_without_publishing(runtime):
    manager, service, alice, _, clients = runtime
    value = config()
    value["tool_views"]["default"] = {
        "tools": {
            "same": {
                "echo": {"aliases": [{"name": "collision"}, {"name": "collision"}]}
            }
        }
    }
    revision = service.preview(alice, None, value)["revision"]
    with pytest.raises(ValueError, match="Duplicate"):
        await manager.apply(alice, revision)
    assert service.store.active(alice)[0] is None
    assert not clients[0].is_connected()


async def test_worker_shutdown_after_ready_and_before_entering(runtime):
    class ExitFailure(BrokenClient):
        async def list_tools(self):
            return []

        async def __aexit__(self, *args):
            self.closed = True
            raise OSError("disconnected during shutdown")

    worker = Connection(ExitFailure(), 0.1)
    await worker.start()
    await worker.close()
    assert worker.client.closed
    unused = Connection(BrokenClient(), 0.1)
    await unused.close()
    assert unused.task.cancelled()
    manager, _, alice, _, _ = runtime
    async with manager.lease(alice) as generation:
        async with manager.lease(alice):
            assert generation.in_flight == 2
        assert generation.in_flight == 1
        assert not generation.idle.is_set()
    assert generation.idle.is_set()
    await manager.close()


async def test_custom_tools_and_hooks_follow_concurrent_caller(runtime):
    from mcp_proxy.identity import principal_context
    from mcp_proxy.user_gateway import UserProvider

    manager, service, alice, bob, _ = runtime
    for principal in (alice, bob):
        value = config(principal.identity.subject)
        value["tool_views"]["default"].update(
            {
                "hooks": {"pre_call": "tests.helpers_owned_tools.owned_hook"},
                "custom_tools": [{"module": "tests.helpers_owned_tools.owned_custom"}],
            }
        )
        draft = service.preview(principal, None, value)
        await manager.apply(principal, draft["revision"])
    provider = UserProvider(manager)

    async def call(principal):
        with principal_context(principal):
            custom = await provider.get_tool("owned_custom")
            direct = await provider.get_tool("echo")
            return str(await custom.run({})), str(
                await direct.run({"value": "ignored"})
            )

    results = await asyncio.gather(call(alice), call(bob))
    assert all("alice:alice" in item and "bob" not in item for item in results[0])
    assert all("bob:bob" in item and "alice" not in item for item in results[1])
    await manager.close()


@pytest.mark.parametrize("section", ["server", "view"])
async def test_preparation_rejects_missing_tool_references(runtime, section):
    manager, service, alice, _, clients = runtime
    value = config()
    if section == "server":
        value["mcp_servers"]["same"]["tools"] = {"absent": {}}
    else:
        value["tool_views"]["default"] = {"tools": {"same": {"absent": {}}}}
    draft = service.preview(alice, None, value)
    with pytest.raises(ValueError, match="not discovered"):
        await manager.apply(alice, draft["revision"])
    assert service.store.active(alice)[0] is None
    assert all(not client.is_connected() for client in clients)


async def test_disabled_tool_references_do_not_require_discovery(runtime):
    manager, service, alice, _, _ = runtime
    value = config()
    value["mcp_servers"]["same"]["tools"] = {"echo": {}, "absent": {"enabled": False}}
    value["tool_views"]["default"] = {
        "tools": {"same": {"echo": {}, "absent": {"enabled": False}}}
    }
    draft = service.preview(alice, None, value)
    await manager.apply(alice, draft["revision"])
    generation = await manager.get(alice)
    assert await generation.mcps["default"].get_tool("echo") is not None
    assert await generation.mcps["default"].get_tool("absent") is None
    await manager.close()
