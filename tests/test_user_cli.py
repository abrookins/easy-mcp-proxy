"""Operator bootstrap/import and remote CLI payload/credential behavior."""

import json
from unittest.mock import AsyncMock, patch

import click
import httpx
import pytest
from click.testing import CliRunner

from mcp_proxy.cli import main
from mcp_proxy.cli.users import import_configuration, remote_request
from mcp_proxy.identity import AccessDenied, Identity
from mcp_proxy.managed_config import materialize_config
from mcp_proxy.user_store import UserStore


def test_local_bootstrap_import_idempotency_and_revoke(tmp_path, monkeypatch):
    runner = CliRunner()
    directory = tmp_path / "state"
    command = ["users", "--state-dir", str(directory)]
    result = runner.invoke(
        main,
        command
        + ["provision", "--issuer", "issuer", "--subject", "alice", "--operator"],
    )
    assert result.exit_code == 0, result.output
    uid = result.output.strip()
    grant = ["grant", uid, "--client", "mcp-proxy-local", "--admin", "--view", "*"]
    assert runner.invoke(main, command + grant).exit_code == 0
    config = tmp_path / "config.yaml"
    config.write_text(
        "mcp_servers:\n  same:\n    command: echo\n    env:\n"
        '      KEY: "${FIXTURE_IMPORT_SECRET}"\ntool_views:\n'
        "  work:\n    include_all: true\n"
    )
    monkeypatch.setenv("FIXTURE_IMPORT_SECRET", "fixture-sensitive")
    args = [
        "import",
        "--issuer",
        "issuer",
        "--subject",
        "alice",
        "--config",
        str(config),
    ]
    result = runner.invoke(main, command + args)
    assert result.exit_code == 0, result.exception
    assert json.loads(result.output)["state"] == "valid"
    result = runner.invoke(main, command + args + ["--apply"])
    assert result.exit_code == 0, result.exception
    revision = json.loads(result.output)["revision"]
    assert "fixture-sensitive" not in result.output
    repeated = import_configuration(directory, "issuer", "alice", config, False)
    assert repeated == {"state": "unchanged", "revision": revision}
    assert "${FIXTURE_IMPORT_SECRET}" in config.read_text()
    store = UserStore(directory)
    principal = store.resolve(Identity("issuer", "alice", "mcp-proxy-local"))
    _, sealed = store.active(principal)
    assert "fixture-sensitive" not in json.dumps(sealed)
    effective = materialize_config(store, principal, sealed)
    assert effective["mcp_servers"]["same"]["env"]["KEY"] == "fixture-sensitive"
    with pytest.raises(AccessDenied):
        import_configuration(directory, "issuer", "another", config)
    import fcntl

    with (directory / "runtime.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(click.ClickException, match="running"):
            import_configuration(directory, "issuer", "alice", config)
    assert (
        runner.invoke(
            main, command + ["revoke", uid, "--client", "mcp-proxy-local"]
        ).exit_code
        == 0
    )
    with pytest.raises(AccessDenied):
        store.active(principal)
    store.close()


def test_remote_cli_input_and_redacted_output(monkeypatch):
    runner = CliRunner()
    command = ["manage", "--url", "https://proxy.test"]
    assert runner.invoke(main, command + ["apply"]).exit_code == 2
    assert (
        runner.invoke(main, command + ["config", "--input", "-"], input="{}").exit_code
        == 2
    )
    assert (
        runner.invoke(main, command + ["preview", "--input", "-"], input="{").exit_code
        == 2
    )
    monkeypatch.setenv("MCP_PROXY_ACCESS_TOKEN", "fixture-token")
    with patch("mcp_proxy.cli.users.remote_request", new_callable=AsyncMock) as remote:
        remote.return_value = {"revision": "one"}
        result = runner.invoke(
            main, command + ["apply", "--input", "-"], input='{"revision":"one"}'
        )
        assert result.exit_code == 0, result.exception
        assert remote.call_args.args[2] == {"revision": "one"}
        assert remote.call_args.args[3] == "fixture-token"
        assert "fixture-token" not in result.output
        assert runner.invoke(main, command + ["config"]).exit_code == 0


async def test_remote_request_https_bearer_oauth_and_failures(tmp_path):
    with pytest.raises(click.ClickException, match="HTTPS"):
        await remote_request("http://remote.test", "config", None, None, tmp_path)
    with (
        patch("mcp_proxy.cli.users.httpx.AsyncClient") as client,
        patch("fastmcp.client.auth.OAuth") as oauth,
    ):
        instance = client.return_value.__aenter__.return_value
        instance.request = AsyncMock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await remote_request(
            "https://proxy.test", "config", None, "fixture", tmp_path
        )
        assert result == {"ok": True}
        assert client.call_args.kwargs["headers"] == {"Authorization": "Bearer fixture"}
        await remote_request(
            "http://localhost:8000",
            "apply",
            {"revision": "one"},
            None,
            tmp_path / "creds",
        )
        assert oauth.call_args.kwargs["token_storage"] is not None
        assert instance.request.call_args.args[0] == "POST"
        instance.request.return_value = httpx.Response(
            403, json={"secret": "never-display"}
        )
        with pytest.raises(click.ClickException, match="HTTP 403") as error:
            await remote_request(
                "https://proxy.test", "status", None, "fixture", tmp_path
            )
        assert "never-display" not in str(error.value)


async def test_stdio_requires_explicit_owner_and_no_global_fallback(
    tmp_path, monkeypatch
):
    from mcp_proxy.identity import current_principal
    from mcp_proxy.user_stdio import serve_owned_stdio

    monkeypatch.delenv("MCP_PROXY_STATE_DIR", raising=False)
    with pytest.raises(ValueError, match="stdio requires"):
        await serve_owned_stdio()
    directory = tmp_path / "stdio"
    monkeypatch.setenv("MCP_PROXY_STATE_DIR", str(directory))
    monkeypatch.setenv("MCP_PROXY_OWNER_ISSUER", "issuer")
    monkeypatch.setenv("MCP_PROXY_OWNER_SUBJECT", "owner")
    store = UserStore(directory)
    uid = store.provision("issuer", "owner")
    with pytest.raises(AccessDenied):
        await serve_owned_stdio()
    store.grant(uid, "mcp-proxy-local", views=["default"])

    async def run(server):
        assert current_principal().user_id == uid
        assert current_principal().identity.client_id == "mcp-proxy-local"
        assert len(await server.list_tools()) == 1  # empty owner's registry help

    with patch("mcp_proxy.user_stdio.FastMCP.run_stdio_async", run):
        await serve_owned_stdio()
    store.close()


def test_oauth_import_cli_secret_input_and_errors(tmp_path, monkeypatch):
    runner = CliRunner()
    command = [
        "users",
        "--state-dir",
        str(tmp_path / "state"),
        "import-oauth",
        "--source",
        str(tmp_path),
    ]
    monkeypatch.delenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", raising=False)
    assert runner.invoke(main, command).exit_code == 1
    monkeypatch.setenv("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET", "fixture-secret")
    assert runner.invoke(main, command).exit_code == 1
    with patch("mcp_proxy.state.migrate_oauth_state", return_value={"state": "valid"}):
        result = runner.invoke(main, command)
        assert result.exit_code == 0
        assert json.loads(result.output)["state"] == "valid"
        assert "fixture-secret" not in result.output
