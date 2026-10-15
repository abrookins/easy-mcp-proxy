"""Local operator-issued API keys bound to an owner and independent grants."""

import hashlib
import json
import secrets
import time
import uuid

from fastmcp.server.auth import AccessToken

from mcp_proxy.auth import CompositeAuthProvider
from mcp_proxy.identity import AccessDenied, Identity


class APIKeys:
    def __init__(self, store):
        self.store = store

    def create(
        self,
        user_id,
        name,
        *,
        token=None,
        views=("default",),
        admin=False,
        expires_in=None,
    ):
        """Generate or explicitly import a key; retain only its SHA-256 digest.

        Generated keys contain 256 random bits. Imports must be existing strong
        random credentials, never passwords. A digest cannot be rebound to a
        different owner, even after revocation.
        """
        if token is None:
            token = "mcp_key_" + secrets.token_urlsafe(32)
        if not (32 <= len(token) <= 4096) or any(c.isspace() for c in token):
            raise ValueError("Key must be 32–4096 characters without whitespace")
        if (
            not name.strip()
            or not views
            or not all(isinstance(v, str) and v for v in views)
        ):
            raise ValueError("Name and explicit views required")
        if expires_in is not None and expires_in <= 0:
            raise ValueError("Expiry must be in the future")
        key_id = uuid.uuid4().hex
        client = "api-key:" + key_id
        now = time.time()
        expires = None if expires_in is None else now + expires_in
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store.transaction():
            if not self.store.db.execute(
                "SELECT id FROM users WHERE id=? AND enabled=1", (user_id,)
            ).fetchone():
                raise ValueError("Enabled, provisioned owner required")
            if self.store.db.execute(
                "SELECT id FROM api_keys WHERE digest=?", (digest,)
            ).fetchone():
                raise ValueError("Key already bound; generate a new key")
            self.store.db.execute(
                "INSERT INTO api_keys VALUES(?,?,?,?,?,?,?,0)",
                (key_id, user_id, client, name, digest, now, expires),
            )
            self.store.db.execute(
                "INSERT INTO grants VALUES(?,?,?,?)",
                (user_id, client, admin, json.dumps(list(views))),
            )
        return {"id": key_id, "client_id": client, "token": token, "expires": expires}

    def identity(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT k.*,u.issuer,u.subject,u.enabled FROM api_keys k "
                "JOIN users u ON u.id=k.user_id WHERE digest=?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        if (
            row["revoked"]
            or not row["enabled"]
            or (row["expires"] is not None and row["expires"] <= time.time())
        ):
            raise AccessDenied("API key expired or revoked")
        return Identity(row["issuer"], row["subject"], row["client"])

    def list(self, user_id):
        with self.store._lock:
            rows = self.store.db.execute(
                "SELECT k.id,k.client,k.name,k.created,k.expires,k.revoked,"
                "g.admin,g.views FROM api_keys k LEFT JOIN grants g "
                "ON g.user_id=k.user_id AND g.client=k.client WHERE k.user_id=? "
                "ORDER BY k.created",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, user_id, key_id):
        with self.store.transaction():
            row = self.store.db.execute(
                "SELECT client FROM api_keys WHERE user_id=? AND id=?",
                (user_id, key_id),
            ).fetchone()
            if row is None:
                raise ValueError("Key not found for this owner")
            self.store.db.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (key_id,))
            for table in ("grants", "sessions"):
                self.store.db.execute(
                    f"DELETE FROM {table} WHERE user_id=? AND client=?",
                    (user_id, row["client"]),
                )


class KeyAuthProvider(CompositeAuthProvider):
    """Recognize bound keys inside FastMCP's bearer middleware as well."""

    def __init__(self, provider, keys):
        super().__init__(oidc_provider=provider)
        self.keys = keys

    async def verify_token(self, token):
        try:
            identity = self.keys.identity(token)
        except AccessDenied:
            return None
        if identity is not None:
            return AccessToken(
                token=token,
                client_id=identity.client_id,
                scopes=[],
                claims={"iss": identity.issuer, "sub": identity.subject},
            )
        return await self.oidc_provider.verify_token(token)
