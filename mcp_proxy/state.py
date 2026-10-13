"""Private persistent state and independent cryptographic keys."""

import base64
import fcntl
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def private_directory(path: Path) -> Path:
    """Create a private directory; reject unsafe pre-existing permissions."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("State directory must be private (mode 0700)")
    return path


def persistent_key(directory: Path, purpose: str) -> bytes:
    """Read or initialize a purpose-specific key under an exclusive file lock.

    Never regenerate corrupt keys: that would silently destroy access to state.
    The lock covers both initialization and reads in competing processes.
    """
    if purpose not in {"oauth", "browser", "config"}:
        raise ValueError("Unknown key purpose")
    directory = private_directory(directory)
    marker = directory / f"{purpose}.initialized"
    path = directory / f"{purpose}.key"
    if marker.exists() and not path.exists():
        raise ValueError("Missing persistent key; restore from backup")
    fd = os.open(
        path,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise ValueError("Key file must be private (mode 0600)")
        value = stream.read()
        if not value:
            if marker.exists():
                raise ValueError("Invalid persistent key; restore from backup")
            value = secrets.token_bytes(32)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if len(value) != 32:
            raise ValueError("Invalid persistent key; restore from backup")
        marker.touch(mode=0o600, exist_ok=True)
        return value


def encryption_key(directory: Path, purpose: str) -> Fernet:
    """Build an authenticated cipher from private persistent key material."""
    return Fernet(base64.urlsafe_b64encode(persistent_key(directory, purpose)))


def oauth_persistence(directory: Path) -> dict:
    """Explicit encrypted FastMCP storage, stable across process restarts."""
    from fastmcp.server.auth.jwt_issuer import derive_jwt_key
    from key_value.aio.stores.filetree import (
        FileTreeStore,
        FileTreeV1CollectionSanitizationStrategy,
        FileTreeV1KeySanitizationStrategy,
    )
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    if (directory / "oauth").exists() and not (directory / "oauth.key").exists():
        raise ValueError("Existing OAuth storage has no signing key; restore backup")
    key = persistent_key(directory, "oauth")
    signing_key = base64.urlsafe_b64encode(key)
    storage_key = derive_jwt_key(
        high_entropy_material=signing_key.decode(),
        salt="fastmcp-storage-encryption-key",
    )
    storage_dir = private_directory(directory / "oauth")
    return {
        "jwt_signing_key": signing_key,
        "client_storage": FernetEncryptionWrapper(
            key_value=FileTreeStore(
                data_directory=storage_dir,
                key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(
                    storage_dir
                ),
                collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
                    storage_dir
                ),
            ),
            fernet=Fernet(storage_key),
            raise_on_decryption_error=True,
        ),
    }


def migrate_oauth_state(
    directory: Path, source: Path, client_secret: str, *, apply=False
):
    """Copy compatible FastMCP v3 default storage without rotating its JWT key.

    The operator must stop the old service and supply its exact OAuth state folder.
    A fingerprint check prevents accidentally importing another installation's data.
    Existing target state is never overwritten; restore/retry is explicit.
    """
    import hashlib
    import json
    import shutil

    from fastmcp.server.auth.jwt_issuer import derive_jwt_key

    signing = derive_jwt_key(
        high_entropy_material=client_secret, salt="fastmcp-jwt-signing-key"
    )
    storage_key = derive_jwt_key(
        high_entropy_material=signing.decode(), salt="fastmcp-storage-encryption-key"
    )
    fingerprint = hashlib.sha256(storage_key).hexdigest()[:12]
    if not source.is_dir() or source.name != fingerprint:
        raise ValueError("Source does not match this installation's OAuth key")
    directory = private_directory(directory)
    with (directory / "runtime.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (directory / "oauth").exists() or (directory / "oauth.key").exists():
            raise ValueError("Target already has OAuth state; restore explicitly")
        paths = list(source.rglob("*"))
        if any(path.is_symlink() for path in paths):
            raise ValueError("OAuth import does not accept symlinks")
        if not apply:
            return {"state": "valid", "files": sum(path.is_file() for path in paths)}
        staging = directory / "oauth-import"
        shutil.copytree(source, staging)
        staging.chmod(0o700)
        # FileTree v1 collection metadata contains absolute paths. Rebase only
        # these metadata fields; encrypted records and token TTLs stay intact.
        for metadata in staging.glob("*-info.json"):
            value = json.loads(metadata.read_text())
            if value.get("version") != 1:
                raise ValueError("Unsupported legacy OAuth storage version")
            relative = Path(value["directory"]).resolve().relative_to(source.resolve())
            value["directory"] = str((directory / "oauth" / relative).resolve())
            metadata.write_text(json.dumps(value))
        for path in staging.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        staging.rename(directory / "oauth")
        (directory / "oauth.initialized").touch(mode=0o600)
        fd = os.open(
            directory / "oauth.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(base64.urlsafe_b64decode(signing))
            stream.flush()
            os.fsync(stream.fileno())
        return {"state": "imported", "signing_key_preserved": True}
