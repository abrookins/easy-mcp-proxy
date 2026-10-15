"""Keys preserve owner/view boundaries through real HTTP and MCP handlers."""

import json
import os

import httpx
import pytest
from click.testing import CliRunner

from mcp_proxy.api_keys import APIKeys, KeyAuthProvider
from mcp_proxy.cli import main
from mcp_proxy.identity import AccessDenied
from mcp_proxy.user_store import UserStore
from tests.test_user_gateway import gateway as gateway
from tests.test_user_gateway import rpc, user_config


def test_key_persistence_revocation_expiry_and_owner_binding(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    store = UserStore(directory)
    uid = store.provision("issuer", "alice")
    other = store.provision("issuer", "bob")
    keys = APIKeys(store)
    key = keys.create(uid, "agent", views=["remote"], expires_in=60)
    identity = keys.identity(key["token"])
    principal = store.resolve(identity, "remote")
    assert principal.user_id == uid
    with pytest.raises(AccessDenied):
        store.resolve(identity)
    assert keys.identity("unknown") is None
    assert keys.list(other) == []
    assert key["token"] not in json.dumps(keys.list(uid))
    assert "digest" not in keys.list(uid)[0]
    assert key["token"].encode() not in (directory / "users.sqlite3").read_bytes()
    with pytest.raises(ValueError, match="already bound"):
        keys.create(other, "other", token=key["token"])
    with pytest.raises(ValueError, match="not found"):
        keys.revoke(other, key["id"])
    store.close()
    store = UserStore(directory)
    keys = APIKeys(store)
    assert store.resolve(keys.identity(key["token"]), "remote").user_id == uid
    store.grant(uid, key["client_id"], views=["default"])
    with pytest.raises(AccessDenied):
        store.authorize(principal)
    store.grant(uid, key["client_id"], views=["remote"])
    with monkeypatch.context() as patch:
        patch.setattr("time.time", lambda: key["expires"] + 1)
        with pytest.raises(AccessDenied):
            keys.identity(key["token"])
        with pytest.raises(AccessDenied):
            store.authorize(principal)
    store.db.execute("UPDATE users SET enabled=0 WHERE id=?", (uid,))
    store.db.commit()
    with pytest.raises(AccessDenied):
        keys.identity(key["token"])
    store.db.execute("UPDATE users SET enabled=1 WHERE id=?", (uid,))
    store.db.commit()
    keys.revoke(uid, key["id"])
    # A later grant cannot resurrect a revoked credential.
    store.grant(uid, key["client_id"], views=["remote"])
    with pytest.raises(AccessDenied):
        store.authorize(principal)
    with pytest.raises(AccessDenied):
        keys.identity(key["token"])
    with pytest.raises(ValueError, match="already bound"):
        keys.create(uid, "reuse", token=key["token"])
    store.close()


@pytest.mark.parametrize(
    "options",
    [
        {"token": "short"},
        {"token": "x" * 32 + " "},
        {"name": ""},
        {"views": []},
        {"views": [""]},
        {"views": [1]},
        {"expires_in": 0},
        {"user_id": "missing"},
    ],
)
def test_key_validation(tmp_path, options):
    store = UserStore(tmp_path / "state")
    uid = store.provision("issuer", "alice")
    with pytest.raises(ValueError):
        APIKeys(store).create(**{"user_id": uid, "name": "agent", **options})
    assert APIKeys(store).list(uid) == []
    store.close()


async def test_key_wire_isolation_admin_and_live_revocation(request):
    app, alice, bob = request.getfixturevalue("gateway")
    tokens = []
    for principal, command in ((alice, "alice-only"), (bob, "bob-only")):
        config = user_config(command)
        config["tool_views"]["remote"] = {"include_all": True}
        draft = app.service.preview(principal, None, config)
        await app.runtime.apply(principal, draft["revision"])
        tokens.append(app.keys.create(principal.user_id, "agent", views=["remote"]))
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app), base_url="https://proxy.test"
        ) as client:
            for key, owner in zip(tokens, ("alice", "bob")):
                client.headers["Authorization"] = "Bearer " + key["token"]
                assert (await client.get("/config/api/identity")).json()[
                    "subject"
                ] == owner
                assert (await client.get("/config/api/config")).status_code == 403
                assert (await client.post("/mcp", json={})).status_code == 401
                assert (
                    await client.post("/view/admin/mcp", json={})
                ).status_code == 401
                result = await rpc(client, "/view/remote/mcp", "tools/list")
                name = next(
                    t["name"] for t in result["result"]["tools"] if "who" in t["name"]
                )
                result = await rpc(
                    client, "/view/remote/mcp", "tools/call", {"name": name}
                )
                assert owner + "-only" in str(result)
                assert ("bob" if owner == "alice" else "alice") + "-only" not in str(
                    result
                )
            app.keys.revoke(bob.user_id, tokens[1]["id"])
            assert (await client.post("/view/remote/mcp", json={})).status_code == 401
            assert (
                await KeyAuthProvider(app.auth, app.keys).verify_token(
                    tokens[1]["token"]
                )
                is None
            )
            # A separate explicit admin key can manage only its owner's config.
            admin = app.keys.create(
                alice.user_id, "admin", admin=True, views=["default", "admin"]
            )
            client.headers["Authorization"] = "Bearer " + admin["token"]
            response = await client.get("/config/api/config")
            assert response.status_code == 200
            assert "alice-only" in response.text and "bob-only" not in response.text
            assert "result" in await rpc(client, "/view/admin/mcp", "tools/list")


def test_cli_secrets_files_import_listing_revoke(tmp_path):
    directory = tmp_path / "state"
    store = UserStore(directory)
    uid = store.provision("issuer", "alice")
    store.close()
    runner = CliRunner()
    command = ["users", "--state-dir", str(directory), "keys"]
    create = command + ["create", uid, "--name", "agent", "--view", "remote"]
    output = tmp_path / "key"
    assert runner.invoke(main, create).exit_code == 2
    assert (
        runner.invoke(
            main, create + ["--input", "-", "--output", str(output)], input="x" * 32
        ).exit_code
        == 2
    )
    result = runner.invoke(main, create + ["--output", str(output)])
    assert result.exit_code == 0, result.output
    key_id = json.loads(result.output)["id"]
    token = output.read_text().strip()
    assert token not in result.output
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert runner.invoke(main, create + ["--output", str(output)]).exit_code == 1
    listed = runner.invoke(main, command + ["list", uid])
    assert listed.exit_code == 0 and key_id in listed.output
    assert token not in listed.output and "digest" not in listed.output
    assert runner.invoke(main, command + ["revoke", uid, key_id]).exit_code == 0
    assert runner.invoke(main, command + ["revoke", uid, "missing"]).exit_code == 1
    imported = runner.invoke(
        main, create + ["--input", "-", "--expires-in", "60"], input="a" * 40 + "\n"
    )
    assert imported.exit_code == 0, imported.output
    assert "a" * 40 not in imported.output
    assert runner.invoke(main, create + ["--input", "-"], input="short").exit_code == 1
