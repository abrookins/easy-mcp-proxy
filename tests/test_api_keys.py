"""Tests for user-owned API keys."""

import stat

from mcp_proxy.api_keys import (
    API_KEY_PREFIX,
    ApiKeyStore,
    ApiKeyVerifier,
    get_api_keys_path,
)


def test_api_keys_path(tmp_path):
    path = get_api_keys_path(tmp_path / "config.yaml")
    assert path == tmp_path / "config.api_keys.json"


def test_create_list_lookup_and_revoke(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    assert store.list_for("a@example.com") == []

    record, key = store.create("A@Example.com", "laptop")

    assert key.startswith(API_KEY_PREFIX)
    assert record["owner"] == "a@example.com"
    assert key not in (tmp_path / "keys.json").read_text()
    assert stat.S_IMODE((tmp_path / "keys.json").stat().st_mode) == 0o600
    assert store.list_for("a@example.com") == [record]
    assert store.list_for("b@example.com") == []
    assert store.lookup(key) == record
    assert store.lookup(key + "x") is None
    assert store.lookup("not-a-managed-key") is None

    assert store.revoke("b@example.com", record["id"]) is False
    assert store.revoke("a@example.com", record["id"]) is True
    assert store.lookup(key) is None


async def test_verifier_authenticates_as_owner(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    record, key = store.create("a@example.com", "ci")
    verifier = ApiKeyVerifier(store)

    token = await verifier.verify_token(key)

    assert token.client_id == f"api-key:{record['id']}"
    assert token.claims["email"] == "a@example.com"
    assert token.claims["email_verified"] is True
    assert await verifier.verify_token("nope") is None
