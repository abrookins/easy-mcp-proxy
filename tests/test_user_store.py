"""Ownership is independent of which users the OAuth provider admits."""

import asyncio
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from mcp_proxy.identity import (
    AccessDenied,
    Identity,
    Principal,
    current_principal,
    principal_context,
)
from mcp_proxy.user_store import Conflict, NotFound, UserStore


@pytest.fixture
def owners(tmp_path):
    store = UserStore(tmp_path / "state")
    principals = []
    for subject in ("alice", "bob"):
        user = store.provision("https://issuer", subject, operator=subject == "alice")
        store.grant(user, "app", admin=True, views=["*"])
        principals.append(store.resolve(Identity("https://issuer", subject, "app")))
    yield store, *principals
    store.close()


def test_verified_identity_requires_subject_not_email():
    for claims in (
        None,
        [],
        {},
        {"email": "owner@example.org"},
        {"iss": " ", "sub": "x"},
    ):
        with pytest.raises(AccessDenied):
            Identity.from_verified_token(
                SimpleNamespace(claims=claims, client_id="app")
            )
    token = SimpleNamespace(claims={"iss": "issuer", "sub": "person"}, client_id="app")
    assert Identity.from_verified_token(token) == Identity("issuer", "person", "app")


async def test_context_concurrent_and_exception_safe(owners):
    _, alice, bob = owners
    with pytest.raises(AccessDenied):
        current_principal()

    async def who(principal):
        with principal_context(principal):
            await asyncio.sleep(0)
            assert current_principal() == principal
            return current_principal().user_id

    assert await asyncio.gather(who(alice), who(bob)) == [alice.user_id, bob.user_id]
    with pytest.raises(RuntimeError), principal_context(alice):
        raise RuntimeError()
    with pytest.raises(AccessDenied):
        current_principal()


def test_broad_oauth_admission_does_not_provision_owner(owners):
    store, alice, bob = owners
    with pytest.raises(AccessDenied, match="provisioned"):
        store.resolve(Identity("https://issuer", "accidentally-admitted", "app"))
    with pytest.raises(AccessDenied):
        store.resolve(Identity("other-issuer", "alice", "app"))
    with pytest.raises(AccessDenied):
        store.resolve(Identity("https://issuer", "alice", "unknown-app"))
    with pytest.raises(AccessDenied):
        store.authorize(replace(bob, user_id=alice.user_id))
    store.authorize(alice, operator=True)
    with pytest.raises(AccessDenied, match="operator"):
        store.authorize(bob, operator=True)
    assert store.provision("https://issuer", "bob", operator=True) == bob.user_id
    with pytest.raises(AccessDenied, match="operator"):
        store.authorize(bob, operator=True)


def test_grants_revocation_and_views(owners):
    store, alice, _ = owners
    store.grant(alice.user_id, "limited", views=["remote"])
    identity = Identity("https://issuer", "alice", "limited")
    limited = store.resolve(identity, "remote")
    store.authorize(limited)
    with pytest.raises(AccessDenied, match="View"):
        store.resolve(identity, "default")
    with pytest.raises(AccessDenied, match="administration"):
        store.draft(limited, None, {})
    store.revoke(alice.user_id, "limited")
    with pytest.raises(AccessDenied):
        store.authorize(limited)
    store.db.execute("UPDATE users SET enabled=0 WHERE id=?", (alice.user_id,))
    store.db.commit()
    with pytest.raises(AccessDenied):
        store.resolve(alice.identity)


def test_input_and_schema_validation(owners, tmp_path):
    store, alice, _ = owners
    for issuer, subject in (("", "user"), ("issuer", " ")):
        with pytest.raises(ValueError):
            store.provision(issuer, subject)
    for client, views in (("", []), ("app", [1])):
        with pytest.raises(ValueError):
            store.grant(alice.user_id, client, views=views)
    with pytest.raises(sqlite3.IntegrityError):
        store.grant("nonexistent", "app")
    path = tmp_path / "future"
    future = UserStore(path)
    future.db.execute("PRAGMA user_version=99")
    future.close()
    with pytest.raises(ValueError, match="version"):
        UserStore(path)


def test_revisions_scope_conflicts_encryption_and_recovery(owners):
    store, alice, bob = owners
    config = {"mcp_servers": {"same-name": {"env": {"TOKEN": "secret-marker"}}}}
    assert store.active(alice) == (None, {"mcp_servers": {}, "tool_views": {}})
    revision = store.draft(alice, None, config)
    competing = store.draft(alice, None, {"mcp_servers": {}})
    with pytest.raises(NotFound):
        store.revision(bob, revision)
    with pytest.raises(ValueError):
        store.transition(alice, revision, "nonsense")
    with pytest.raises(Conflict):
        store.transition(alice, revision, "active")
    store.transition(alice, revision, "preparing")
    store.transition(alice, revision, "preparing")
    store.transition(alice, revision, "active")
    store.transition(alice, revision, "active")
    assert store.active(alice) == (revision, config)
    assert store.active(bob)[0] is None
    for action in (
        lambda: store.draft(alice, None, {}),
        lambda: store.transition(alice, competing, "preparing"),
        lambda: store.transition(alice, revision, "failed"),
    ):
        with pytest.raises(Conflict):
            action()
    assert store.revision(alice, competing)["state"] == "draft"
    next_revision = store.draft(alice, revision, {})
    store.transition(alice, next_revision, "preparing")
    store.recover()
    assert store.revision(alice, next_revision)["error"] == "interrupted"
    failed = store.draft(alice, revision, {})
    store.transition(alice, failed, "preparing")
    store.transition(alice, failed, "failed")
    assert store.history(bob) == []
    assert len(store.history(alice)) == 4
    assert "config" not in store.history(alice)[0]
    assert b"secret-marker" not in (store.directory / "users.sqlite3").read_bytes()
    reopened = UserStore(store.directory)
    assert reopened.active(alice) == (revision, config)
    reopened.close()


def test_secret_ownership_and_revocation(owners):
    store, alice, bob = owners
    secret_id = store.put_secret(alice, "credential-marker")
    assert store.get_secret(alice, secret_id) == "credential-marker"
    with pytest.raises(NotFound):
        store.get_secret(bob, secret_id)
    store.delete_secret(bob, secret_id)
    assert store.get_secret(alice, secret_id) == "credential-marker"
    store.delete_secret(alice, secret_id)
    with pytest.raises(NotFound):
        store.get_secret(alice, secret_id)
    assert b"credential-marker" not in (store.directory / "users.sqlite3").read_bytes()


def test_forged_principal_is_rechecked(owners):
    store, alice, bob = owners
    forged = Principal(alice.user_id, bob.identity)
    for action in (
        lambda: store.active(forged),
        lambda: store.history(forged),
        lambda: store.put_secret(forged, "value"),
        lambda: store.get_secret(forged, "id"),
        lambda: store.delete_secret(forged, "id"),
    ):
        with pytest.raises(AccessDenied):
            action()


def test_login_expiry_single_use_and_session_restart(owners, monkeypatch):
    store, alice, _ = owners
    now = 1000
    monkeypatch.setattr("mcp_proxy.user_store.time.time", lambda: now)
    store.begin_login("state", "private-verifier")
    reopened = UserStore(store.directory)
    assert reopened.consume_login("state") == "private-verifier"
    with pytest.raises(AccessDenied):
        store.consume_login("state")
    store.begin_login("expired", "private")
    session = store.create_session(alice)
    assert reopened.session_principal(session) == alice
    now += 601
    with pytest.raises(AccessDenied):
        reopened.consume_login("expired")
    store.begin_login("new", "next")
    now += 86400
    with pytest.raises(AccessDenied):
        reopened.session_principal(session)
    store.create_session(alice)
    reopened.close()


def test_retention_keeps_active_and_scopes_audit(owners):
    store, alice, bob = owners
    first = store.draft(alice, None, {})
    store.transition(alice, first, "preparing")
    store.transition(alice, first, "active")
    for _ in range(105):
        store.draft(alice, first, {})
    assert len(store.history(alice)) == 100
    assert store.active(alice)[0] == first
    assert store.revision(alice, first)["state"] == "active"
    assert store.db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 101
    assert len(store.diagnostics(alice)) == 100
    assert store.diagnostics(bob) == []


def test_any_view_resolution_never_assumes_default_access(owners):
    store, alice, bob = owners
    assert store.resolve(alice.identity, None).view == "default"
    store.grant(bob.user_id, "app", views=["limited"])
    assert store.resolve(bob.identity, None).view == "limited"
    store.grant(bob.user_id, "app", views=[])
    with pytest.raises(AccessDenied, match="No view"):
        store.resolve(bob.identity, None)
    store.revoke(bob.user_id, "app")
    with pytest.raises(AccessDenied, match="No view"):
        store.resolve(bob.identity, None)
