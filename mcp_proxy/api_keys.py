"""User-owned API keys managed through the web UI.

Keys are stored as SHA-256 hashes in a JSON file next to the config file.
Each key belongs to the email of the user who created it, and authenticates
as that user when presented as a Bearer token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import AccessToken

API_KEY_PREFIX = "mcpp_"
PUBLIC_FIELDS = ("id", "name", "owner", "prefix", "created_at")


def get_api_keys_path(config_path: Path) -> Path:
    """Get the path for the API key store (JSON next to YAML)."""
    return config_path.with_suffix(".api_keys.json")


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in PUBLIC_FIELDS}


class ApiKeyStore:
    """File-backed store of hashed, user-owned API keys."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path) as f:
            return json.load(f).get("keys", [])

    def _save(self, records: list[dict[str, Any]]) -> None:
        with open(self.path, "w") as f:
            json.dump({"keys": records}, f, indent=2)
        self.path.chmod(0o600)

    def list_for(self, owner: str) -> list[dict[str, Any]]:
        """List public metadata for keys owned by `owner`."""
        owner = owner.casefold()
        return [_public(r) for r in self._load() if r["owner"] == owner]

    def create(self, owner: str, name: str) -> tuple[dict[str, Any], str]:
        """Create a key for `owner`. Returns (metadata, plaintext key)."""
        key = API_KEY_PREFIX + secrets.token_urlsafe(32)
        record = {
            "id": secrets.token_hex(8),
            "name": name,
            "owner": owner.casefold(),
            "prefix": key[: len(API_KEY_PREFIX) + 6],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hash": _hash_key(key),
        }
        records = self._load()
        records.append(record)
        self._save(records)
        return _public(record), key

    def revoke(self, owner: str, key_id: str) -> bool:
        """Delete a key owned by `owner`. Returns False if not found."""
        owner = owner.casefold()
        records = self._load()
        remaining = [
            r for r in records if not (r["id"] == key_id and r["owner"] == owner)
        ]
        if len(remaining) == len(records):
            return False
        self._save(remaining)
        return True

    def lookup(self, key: str) -> dict[str, Any] | None:
        """Return metadata for a plaintext key, or None if unknown."""
        if not key.startswith(API_KEY_PREFIX):
            return None
        digest = _hash_key(key)
        for record in self._load():
            if hmac.compare_digest(record["hash"], digest):
                return _public(record)
        return None


class ApiKeyVerifier:
    """Token verifier that authenticates managed API keys as their owner."""

    def __init__(self, store: ApiKeyStore):
        self.store = store

    async def verify_token(self, token: str) -> "AccessToken | None":
        from fastmcp.server.auth.auth import AccessToken

        record = self.store.lookup(token)
        if record is None:
            return None
        return AccessToken(
            token=token,
            client_id=f"api-key:{record['id']}",
            scopes=[],
            claims={
                "sub": record["owner"],
                "email": record["owner"],
                "email_verified": True,
                "api_key_id": record["id"],
            },
        )
