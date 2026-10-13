"""Durable key and encrypted OAuth state behavior."""

import os
import subprocess
import sys

import pytest

from mcp_proxy.state import encryption_key, oauth_persistence, persistent_key


def test_key_survives_process_and_separates_purposes(tmp_path):
    directory = tmp_path / "state"
    key = persistent_key(directory, "browser")
    script = (
        "from pathlib import Path; from mcp_proxy.state import persistent_key; "
        "import sys; sys.stdout.buffer.write(persistent_key(Path(sys.argv[1]),"
        " 'browser'))"
    )
    assert (
        subprocess.check_output([sys.executable, "-c", script, str(directory)]) == key
    )
    assert persistent_key(directory, "config") != key
    cipher = encryption_key(directory, "config")
    assert cipher.decrypt(cipher.encrypt(b"private")) == b"private"
    assert (directory / "browser.key").stat().st_mode & 0o777 == 0o600


def test_reject_unsafe_or_corrupt_state(tmp_path):
    with pytest.raises(ValueError, match="purpose"):
        persistent_key(tmp_path, "../elsewhere")
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="directory"):
        persistent_key(directory, "browser")
    directory.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(directory)
    with pytest.raises(ValueError, match="directory"):
        persistent_key(link, "browser")
    persistent_key(directory, "browser")
    path = directory / "browser.key"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="Key file"):
        persistent_key(directory, "browser")
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Invalid persistent key"):
        persistent_key(directory, "browser")


async def test_oauth_storage_encrypted_and_reopened(tmp_path):
    directory = tmp_path / "state"
    first = oauth_persistence(directory)
    await first["client_storage"].put("token", {"secret": "sensitive-marker"})
    second = oauth_persistence(directory)
    assert first["jwt_signing_key"] == second["jwt_signing_key"]
    assert await second["client_storage"].get("token") == {"secret": "sensitive-marker"}
    for path in (directory / "oauth").rglob("*"):
        if path.is_file():
            assert b"sensitive-marker" not in path.read_bytes()


def test_oidc_provider_uses_explicit_state(tmp_path, monkeypatch):
    from unittest.mock import patch

    from mcp_proxy.auth import _create_oidc_provider

    monkeypatch.setenv("MCP_PROXY_STATE_DIR", str(tmp_path / "state"))
    with patch("fastmcp.server.auth.oidc_proxy.OIDCProxy") as factory:
        _create_oidc_provider()
        assert factory.call_args.kwargs["client_storage"] is not None
        assert factory.call_args.kwargs["jwt_signing_key"]
    assert os.stat(tmp_path / "state").st_mode & 0o777 == 0o700


def test_actual_process_restart_access_refresh_browser_and_discovery(tmp_path):
    import json

    directory = tmp_path / "restart-state"
    command = [sys.executable, "-m", "tests.helpers_user_restart", str(directory)]
    subprocess.run(command + ["seed"], check=True, capture_output=True, text=True)
    result = subprocess.run(command + ["verify"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout).values()) == {"passed"}


def test_missing_or_empty_initialized_keys_never_regenerate(tmp_path):
    directory = tmp_path / "private"
    persistent_key(directory, "oauth")
    path = directory / "oauth.key"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="Invalid persistent key"):
        persistent_key(directory, "oauth")
    path.unlink()
    with pytest.raises(ValueError, match="Missing persistent key"):
        persistent_key(directory, "oauth")
    assert not path.exists()


async def test_import_legacy_oauth_retains_signing_and_encrypted_records(
    tmp_path, monkeypatch
):
    import fastmcp
    from fastmcp.server.auth.oauth_proxy import OAuthProxy
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyUrl

    from mcp_proxy.state import migrate_oauth_state

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path / "legacy")
    options = dict(
        upstream_authorization_endpoint="https://idp.test/auth",
        upstream_token_endpoint="https://idp.test/token",
        upstream_client_id="fixture",
        upstream_client_secret="fixture-secret",
        token_verifier=StaticTokenVerifier(tokens={}),
        base_url="https://proxy.test",
    )
    before = OAuthProxy(**options)
    before.get_routes(mcp_path="/mcp")
    await before.register_client(
        OAuthClientInformationFull(
            client_id="retained", redirect_uris=[AnyUrl("http://localhost/callback")]
        )
    )
    token = before.jwt_issuer.issue_access_token("retained", [], "jti")
    source = next((tmp_path / "legacy/oauth-proxy").iterdir())
    target = tmp_path / "managed"
    assert migrate_oauth_state(target, source, "fixture-secret")["state"] == "valid"
    assert not (target / "oauth.key").exists()
    with pytest.raises(ValueError, match="Source does not match"):
        migrate_oauth_state(target, source, "wrong")
    link = source / "link"
    link.symlink_to(source / "elsewhere")
    with pytest.raises(ValueError, match="symlinks"):
        migrate_oauth_state(target, source, "fixture-secret")
    link.unlink()
    result = migrate_oauth_state(target, source, "fixture-secret", apply=True)
    assert result["signing_key_preserved"]
    after = OAuthProxy(**options, **oauth_persistence(target))
    after.get_routes(mcp_path="/mcp")
    assert after.jwt_issuer.verify_token(token)["client_id"] == "retained"
    assert (await after.get_client("retained")).client_id == "retained"
    with pytest.raises(ValueError, match="already has"):
        migrate_oauth_state(target, source, "fixture-secret", apply=True)
    (target / "oauth.key").unlink()
    with pytest.raises(ValueError, match="no signing key"):
        oauth_persistence(target)


def test_oauth_import_rejects_unknown_filetree_version(tmp_path):
    import hashlib
    import json

    from fastmcp.server.auth.jwt_issuer import derive_jwt_key

    from mcp_proxy.state import migrate_oauth_state

    signing = derive_jwt_key(
        high_entropy_material="fixture", salt="fastmcp-jwt-signing-key"
    )
    storage = derive_jwt_key(
        high_entropy_material=signing.decode(), salt="fastmcp-storage-encryption-key"
    )
    source = tmp_path / hashlib.sha256(storage).hexdigest()[:12]
    source.mkdir()
    (source / "collection-info.json").write_text(json.dumps({"version": 99}))
    with pytest.raises(ValueError, match="Unsupported legacy"):
        migrate_oauth_state(tmp_path / "target", source, "fixture", apply=True)
    assert not (tmp_path / "target/oauth.key").exists()
