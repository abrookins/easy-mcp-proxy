"""Local ownership bootstrap and remote user-configuration administration."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import click
import httpx

from mcp_proxy.config import load_config
from mcp_proxy.identity import Identity
from mcp_proxy.managed_config import ConfigService
from mcp_proxy.state import oauth_persistence
from mcp_proxy.user_store import UserStore


@click.group()
@click.option(
    "--state-dir",
    type=click.Path(path_type=Path),
    envvar="MCP_PROXY_STATE_DIR",
    required=True,
)
@click.pass_context
def users(ctx, state_dir):
    """Provision identities locally. These commands require host access."""
    ctx.obj = state_dir


@users.command()
@click.option("--issuer", required=True)
@click.option("--subject", required=True)
@click.option("--operator", is_flag=True)
@click.pass_obj
def provision(directory, issuer, subject, operator):
    """Create an explicit owner; never let first login claim existing config."""
    store = UserStore(directory)
    try:
        click.echo(store.provision(issuer, subject, operator=operator))
    finally:
        store.close()


@users.command("grant")
@click.argument("user_id")
@click.option("--client", required=True)
@click.option("--admin", is_flag=True)
@click.option("--view", multiple=True, default=("default",))
@click.pass_obj
def grant_client(directory, user_id, client, admin, view):
    """Grant a registered OAuth application access to this user's views."""
    store = UserStore(directory)
    try:
        store.grant(user_id, client, admin=admin, views=view)
        click.echo("Grant saved")
    finally:
        store.close()


@users.command("revoke")
@click.argument("user_id")
@click.option("--client", required=True)
@click.pass_obj
def revoke_client(directory, user_id, client):
    """Revoke an application's grant and browser sessions."""
    store = UserStore(directory)
    try:
        store.revoke(user_id, client)
        click.echo("Grant revoked")
    finally:
        store.close()


def import_configuration(directory, issuer, subject, config_path, dry_run=True):
    """Import as an explicit existing owner, with encrypted durable revisions."""
    import fcntl
    import hashlib

    store = UserStore(directory)
    try:
        # Online edits must use the live activation API.
        with (directory / "runtime.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise click.ClickException(
                    "Service is running; use remote preview/apply"
                ) from None
            principal = store.resolve(Identity(issuer, subject, "mcp-proxy-local"))
            config = load_config(config_path).model_dump(exclude_none=True)
            config.pop("cache_secret", None)
            config.pop("cache_base_url", None)
            service = ConfigService(store)
            current, previous = store.active(principal)
            from mcp_proxy.managed_config import (
                materialize_config,
                validate_managed_config,
            )

            validate_managed_config(store, principal, config, previous)
            if materialize_config(store, principal, previous) == config:
                return {"state": "unchanged", "revision": current}
            digest = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()
            if dry_run:
                return {
                    "state": "valid",
                    "source_hash": digest,
                    "user_id": principal.user_id,
                }
            # Source YAML/overrides remain untouched; prior committed revision is
            # retained for rollback, including encrypted credential references.
            revision = service.preview(principal, current, config)["revision"]
            store.transition(principal, revision, "preparing")
            store.transition(principal, revision, "active")
            return {"state": "imported", "revision": revision, "source_hash": digest}
    finally:
        store.close()


@users.command("import")
@click.option("--issuer", required=True)
@click.option("--subject", required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option(
    "--apply", is_flag=True, help="Import after validating (default: dry run)."
)
@click.pass_obj
def import_config(directory, issuer, subject, config_path, apply):
    """Import legacy YAML and overrides while the managed runtime is stopped."""
    value = import_configuration(directory, issuer, subject, config_path, not apply)
    click.echo(json.dumps(value))


async def remote_request(url, action, payload, token, directory):
    from fastmcp.client.auth import OAuth

    parsed = urlsplit(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise click.ClickException("Use HTTPS, or HTTP on loopback for development")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    auth = None
    if not token:
        auth = OAuth(
            mcp_url=url.rstrip("/") + "/mcp",
            client_name="MCP Proxy Admin CLI",
            token_storage=oauth_persistence(directory)["client_storage"],
        )
    async with httpx.AsyncClient(auth=auth, headers=headers, timeout=60) as client:
        method = "GET" if payload is None else "POST"
        response = await client.request(
            method, url.rstrip("/") + "/config/api/" + action, json=payload
        )
        if response.is_error:
            raise click.ClickException(
                f"Management request failed (HTTP {response.status_code})"
            )
        return response.json()


@click.command("manage")
@click.option("--url", required=True, envvar="MCP_PROXY_URL")
@click.option(
    "--credential-dir",
    type=click.Path(path_type=Path),
    default=lambda: Path.home() / ".local/state/mcp-proxy-client",
)
@click.argument(
    "action",
    type=click.Choice(
        [
            "identity",
            "config",
            "history",
            "status",
            "preview",
            "apply",
            "probe",
            "rollback",
        ]
    ),
)
@click.option(
    "--input",
    "input_path",
    type=click.File("r"),
    help="JSON request file, or - for stdin. Secrets are never CLI arguments.",
)
def manage(url, credential_dir, action, input_path):
    """Manage the logged-in user's remote configuration using OAuth."""
    writes = {"preview", "apply", "probe", "rollback"}
    if (action in writes) != (input_path is not None):
        raise click.UsageError("Provide --input for a write operation only")
    try:
        payload = json.load(input_path) if input_path else None
    except ValueError:
        raise click.UsageError("Input must be valid JSON") from None
    value = asyncio.run(
        remote_request(
            url,
            action,
            payload,
            os.environ.get("MCP_PROXY_ACCESS_TOKEN"),
            credential_dir,
        )
    )
    click.echo(json.dumps(value, indent=2))


@users.command("import-oauth")
@click.option("--source", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--apply", is_flag=True)
@click.pass_obj
def import_oauth(directory, source, apply):
    """Copy stopped FastMCP v3 default OAuth state, preserving existing tokens."""
    from mcp_proxy.state import migrate_oauth_state

    secret = os.environ.get("FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET")
    if not secret:
        raise click.ClickException(
            "Set the existing Auth0 client secret in the environment"
        )
    try:
        value = migrate_oauth_state(directory, source, secret, apply=apply)
    except (ValueError, OSError):
        raise click.ClickException(
            "OAuth import failed; verify source/key and empty stopped target"
        ) from None
    click.echo(json.dumps(value))
