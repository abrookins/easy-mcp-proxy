"""Encrypted, revisioned user configuration with explicit local provisioning."""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from mcp_proxy.identity import AccessDenied, Identity, Principal
from mcp_proxy.state import encryption_key, private_directory


class Conflict(ValueError):
    """The reviewed base revision is no longer current."""


class NotFound(LookupError):
    """No record exists within the current user's namespace."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, operator INTEGER NOT NULL DEFAULT 0,
 active TEXT, UNIQUE(issuer, subject)
);
CREATE TABLE IF NOT EXISTS grants (
 user_id TEXT NOT NULL REFERENCES users(id), client TEXT NOT NULL,
 admin INTEGER NOT NULL, views TEXT NOT NULL,
 PRIMARY KEY(user_id, client)
);
CREATE TABLE IF NOT EXISTS revisions (
 user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL,
 base TEXT, payload BLOB NOT NULL, state TEXT NOT NULL,
 actor TEXT NOT NULL, created REAL NOT NULL, error TEXT,
 PRIMARY KEY(user_id, id)
);
CREATE TABLE IF NOT EXISTS secrets (
 user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL,
 payload BLOB NOT NULL, PRIMARY KEY(user_id, id)
);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 client TEXT NOT NULL, expires REAL NOT NULL, email TEXT
);
CREATE TABLE IF NOT EXISTS audit (
 sequence INTEGER PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 actor TEXT NOT NULL, event TEXT NOT NULL, revision TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS browser_logins (
 state TEXT PRIMARY KEY, verifier BLOB NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 client TEXT NOT NULL UNIQUE, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 created REAL NOT NULL, expires REAL, revoked INTEGER NOT NULL DEFAULT 0
);
"""


class UserStore:
    """One process may run the proxy; transactions protect competing admin edits.

    Provisioning methods are local operator APIs, never remote administration tools.
    All other entry points re-check the principal against durable account state.
    """

    def __init__(self, directory: Path, admin_emails=()):
        # Best effort: a verified email in this list grants configuration
        # administration. Users without an email fall back to their grants.
        self.admin_emails = frozenset(e.casefold() for e in admin_emails)
        self.directory = private_directory(directory)
        self.cipher = encryption_key(directory, "config")
        self._lock = threading.RLock()
        path = directory / "users.sqlite3"
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError("Unsupported configuration database version")
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(sessions)")}
        if "email" not in columns:
            self.db.execute("ALTER TABLE sessions ADD COLUMN email TEXT")
        self.db.execute("PRAGMA user_version = 1")
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def _encode(self, value) -> bytes:
        return self.cipher.encrypt(json.dumps(value, sort_keys=True).encode())

    def _decode(self, value):
        return json.loads(self.cipher.decrypt(value))

    def provision(self, issuer: str, subject: str, *, operator: bool = False) -> str:
        """Explicitly create an owner; repeated imports never change privilege."""
        if not issuer.strip() or not subject.strip():
            raise ValueError("Issuer and subject required")
        with self.transaction():
            self.db.execute(
                "INSERT OR IGNORE INTO users(id,issuer,subject,operator) "
                "VALUES(?,?,?,?)",
                (uuid.uuid4().hex, issuer, subject, operator),
            )
            return self.db.execute(
                "SELECT id FROM users WHERE issuer=? AND subject=?", (issuer, subject)
            ).fetchone()[0]

    def grant(self, user_id: str, client: str, *, admin=False, views=()):
        """Local operator sets an explicit application's permissions."""
        if not client or not all(isinstance(v, str) for v in views):
            raise ValueError("Client and view names required")
        with self.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO grants VALUES(?,?,?,?)",
                (user_id, client, admin, json.dumps(list(views))),
            )

    def revoke(self, user_id: str, client: str):
        with self.transaction():
            self.db.execute(
                "DELETE FROM grants WHERE user_id=? AND client=?", (user_id, client)
            )
            self.db.execute(
                "DELETE FROM sessions WHERE user_id=? AND client=?", (user_id, client)
            )

    def resolve(self, identity: Identity, view: str | None = "default") -> Principal:
        with self._lock:
            row = self.db.execute(
                "SELECT id FROM users WHERE issuer=? AND subject=? AND enabled=1",
                (identity.issuer, identity.subject),
            ).fetchone()
        if row is None:
            raise AccessDenied("Account is not provisioned")
        if view is None:
            grant = self.db.execute(
                "SELECT views FROM grants WHERE user_id=? AND client=?",
                (row[0], identity.client_id),
            ).fetchone()
            allowed = json.loads(grant[0]) if grant else []
            if not allowed:
                raise AccessDenied("No view is authorized")
            view = "default" if "*" in allowed else allowed[0]
        principal = Principal(row[0], identity, view)
        self.authorize(principal)
        return principal

    def authorize(self, principal: Principal, *, admin=False, operator=False):
        with self._lock:
            if principal.identity.client_id.startswith("api-key:"):
                key = self.db.execute(
                    "SELECT id FROM api_keys WHERE user_id=? AND client=? "
                    "AND revoked=0 AND (expires IS NULL OR expires>?)",
                    (principal.user_id, principal.identity.client_id, time.time()),
                ).fetchone()
                if key is None:
                    raise AccessDenied("API key expired or revoked")
            row = self.db.execute(
                "SELECT g.admin,g.views,u.operator FROM users u JOIN grants g "
                "ON u.id=g.user_id WHERE u.id=? AND u.issuer=? AND u.subject=? "
                "AND u.enabled=1 AND g.client=?",
                (
                    principal.user_id,
                    principal.identity.issuer,
                    principal.identity.subject,
                    principal.identity.client_id,
                ),
            ).fetchone()
        if row is None:
            raise AccessDenied("Application is not authorized")
        if admin and not (row["admin"] or self.is_admin_email(principal)):
            raise AccessDenied("Configuration administration permission required")
        if operator and not row["operator"]:
            raise AccessDenied("Installation operator permission required")
        views = json.loads(row["views"])
        if not admin and principal.view not in views and "*" not in views:
            raise AccessDenied("View is not authorized")

    def is_admin_email(self, principal: Principal) -> bool:
        email = principal.identity.email
        return email is not None and email.casefold() in self.admin_emails

    def access(self, principal: Principal) -> dict:
        """Describe the caller's own grant so clients can offer allowed actions."""
        self.authorize(principal)
        with self._lock:
            row = self.db.execute(
                "SELECT g.admin,g.views,u.operator FROM users u JOIN grants g "
                "ON u.id=g.user_id WHERE u.id=? AND g.client=?",
                (principal.user_id, principal.identity.client_id),
            ).fetchone()
        return {
            "admin": bool(row["admin"]) or self.is_admin_email(principal),
            "operator": bool(row["operator"]),
            "views": json.loads(row["views"]),
        }

    def active(self, principal: Principal):
        self.authorize(principal)
        with self._lock:
            revision = self.db.execute(
                "SELECT active FROM users WHERE id=?", (principal.user_id,)
            ).fetchone()[0]
            if revision is None:
                return None, {"mcp_servers": {}, "tool_views": {}}
            return revision, self.revision(principal, revision)["config"]

    def revision(self, principal: Principal, revision: str) -> dict:
        self.authorize(principal)
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM revisions WHERE user_id=? AND id=?",
                (principal.user_id, revision),
            ).fetchone()
        if row is None:
            raise NotFound("Revision not found")
        value = dict(row)
        value["config"] = self._decode(value.pop("payload"))
        return value

    def draft(self, principal: Principal, base: str | None, config: dict) -> str:
        self.authorize(principal, admin=True)
        revision = uuid.uuid4().hex
        with self.transaction():
            self.authorize(principal, admin=True)
            self._check_base(principal, base)
            self.db.execute(
                "INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?)",
                (
                    principal.user_id,
                    revision,
                    base,
                    self._encode(config),
                    "draft",
                    principal.identity.client_id,
                    time.time(),
                    None,
                ),
            )
            self._audit(principal, "preview", revision)
            self._prune(principal.user_id)
        return revision

    def _check_base(self, principal: Principal, base: str | None):
        active = self.db.execute(
            "SELECT active FROM users WHERE id=?", (principal.user_id,)
        ).fetchone()[0]
        if active != base:
            raise Conflict("Configuration changed; preview the latest revision")

    def transition(self, principal: Principal, revision: str, state: str):
        """Persist preparation/activation; publishing runtime follows active commit."""
        self.authorize(principal, admin=True)
        if state not in {"preparing", "active", "failed"}:
            raise ValueError("Invalid activation state")
        with self.transaction():
            self.authorize(principal, admin=True)
            row = self.revision(principal, revision)
            expected = {
                "preparing": "draft",
                "active": "preparing",
                "failed": "preparing",
            }
            if row["state"] == state:
                return
            if row["state"] != expected[state]:
                raise Conflict("Invalid activation transition")
            if state != "failed":
                self._check_base(principal, row["base"])
            self.db.execute(
                "UPDATE revisions SET state=?,error=CASE WHEN ?='failed' "
                "THEN 'preparation_failed' ELSE NULL END WHERE user_id=? AND id=?",
                (state, state, principal.user_id, revision),
            )
            if state == "active":
                self.db.execute(
                    "UPDATE users SET active=? WHERE id=?",
                    (revision, principal.user_id),
                )
            self._audit(principal, state, revision)

    def recover(self):
        """On single-process startup, preparations never committed are abandoned."""
        with self.transaction():
            self.db.execute(
                "UPDATE revisions SET state='failed',error='interrupted' "
                "WHERE state='preparing'"
            )

    def history(self, principal: Principal) -> list[dict]:
        self.authorize(principal, admin=True)
        with self._lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT id,base,state,actor,created,error FROM revisions "
                    "WHERE user_id=? ORDER BY created DESC LIMIT 100",
                    (principal.user_id,),
                )
            ]

    def _audit(self, principal: Principal, event: str, revision: str):
        self.db.execute(
            "INSERT INTO audit(user_id,actor,event,revision,created) VALUES(?,?,?,?,?)",
            (
                principal.user_id,
                principal.identity.client_id,
                event,
                revision,
                time.time(),
            ),
        )
        self.db.execute(
            "DELETE FROM audit WHERE user_id=? AND sequence NOT IN "
            "(SELECT sequence FROM audit WHERE user_id=? "
            "ORDER BY sequence DESC LIMIT 1000)",
            (principal.user_id, principal.user_id),
        )

    def _prune(self, user_id: str):
        """Bound revisions, retaining the active and any preparing generation."""
        self.db.execute(
            "DELETE FROM revisions WHERE user_id=? AND state!='preparing' "
            "AND id NOT IN (SELECT id FROM revisions WHERE user_id=? "
            "ORDER BY created DESC LIMIT 100) "
            "AND id IS NOT (SELECT active FROM users WHERE id=?)",
            (user_id, user_id, user_id),
        )

    def diagnostics(self, principal: Principal) -> list[dict]:
        self.authorize(principal, admin=True)
        with self._lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT actor,event,revision,created FROM audit WHERE user_id=? "
                    "ORDER BY sequence DESC LIMIT 100",
                    (principal.user_id,),
                )
            ]

    def put_secret(self, principal: Principal, value: str) -> str:
        self.authorize(principal, admin=True)
        secret_id = uuid.uuid4().hex
        with self.transaction():
            self.authorize(principal, admin=True)
            self.db.execute(
                "INSERT INTO secrets VALUES(?,?,?)",
                (principal.user_id, secret_id, self._encode(value)),
            )
        return secret_id

    def get_secret(self, principal: Principal, secret_id: str) -> str:
        self.authorize(principal)
        with self._lock:
            row = self.db.execute(
                "SELECT payload FROM secrets WHERE user_id=? AND id=?",
                (principal.user_id, secret_id),
            ).fetchone()
        if row is None:
            raise NotFound("Secret unavailable")
        return self._decode(row[0])

    def delete_secret(self, principal: Principal, secret_id: str):
        self.authorize(principal, admin=True)
        with self.transaction():
            self.authorize(principal, admin=True)
            self.db.execute(
                "DELETE FROM secrets WHERE user_id=? AND id=?",
                (principal.user_id, secret_id),
            )

    def begin_login(self, state: str, verifier: str):
        with self.transaction():
            self.db.execute(
                "DELETE FROM browser_logins WHERE expires<?", (time.time(),)
            )
            self.db.execute(
                "INSERT INTO browser_logins VALUES(?,?,?)",
                (state, self._encode(verifier), time.time() + 600),
            )

    def consume_login(self, state: str) -> str:
        with self.transaction():
            row = self.db.execute(
                "SELECT verifier,expires FROM browser_logins WHERE state=?", (state,)
            ).fetchone()
            self.db.execute("DELETE FROM browser_logins WHERE state=?", (state,))
        if row is None or row["expires"] < time.time():
            raise AccessDenied("Login expired; start again")
        return self._decode(row["verifier"])

    def create_session(self, principal: Principal) -> str:
        import secrets

        self.authorize(principal, admin=True)
        session = secrets.token_urlsafe(32)
        with self.transaction():
            self.authorize(principal, admin=True)
            self.db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            self.db.execute(
                "INSERT INTO sessions(id,user_id,client,expires,email) "
                "VALUES(?,?,?,?,?)",
                (
                    session,
                    principal.user_id,
                    principal.identity.client_id,
                    time.time() + 86400,
                    principal.identity.email,
                ),
            )
        return session

    def session_principal(self, session: str) -> Principal:
        with self._lock:
            row = self.db.execute(
                "SELECT u.issuer,u.subject,s.client,s.email FROM sessions s "
                "JOIN users u "
                "ON u.id=s.user_id WHERE s.id=? AND s.expires>? AND u.enabled=1",
                (session, time.time()),
            ).fetchone()
        if row is None:
            raise AccessDenied("Browser session expired")
        return self.resolve(
            Identity(row["issuer"], row["subject"], row["client"], row["email"])
        )

    def logout(self, session: str):
        with self.transaction():
            self.db.execute("DELETE FROM sessions WHERE id=?", (session,))
