"""Host-local API key issuance; secret values never appear in command arguments."""

import json
import os
from contextlib import ExitStack
from pathlib import Path

import click

from mcp_proxy.api_keys import APIKeys
from mcp_proxy.user_store import UserStore


@click.group()
def keys():
    """Create, inspect and revoke keys explicitly bound to a provisioned owner."""


@keys.command("create")
@click.argument("user_id")
@click.option("--name", required=True)
@click.option("--view", multiple=True, required=True)
@click.option("--admin", is_flag=True)
@click.option("--expires-in", type=click.IntRange(min=1), help="Lifetime in seconds.")
@click.option(
    "--input",
    "source",
    type=click.File("r"),
    help="Import a key from a file or - (stdin).",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    help="Write a generated key to a new private file.",
)
@click.pass_obj
def create(directory, user_id, name, view, admin, expires_in, source, output):
    """Generate a key with --output, or bind an existing strong key with --input."""
    if (source is None) == (output is None):
        raise click.UsageError("Choose exactly one of --input or --output")
    with ExitStack() as stack:
        store = UserStore(directory)
        stack.callback(store.close)
        try:
            stream = None
            if output is not None:
                fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                stream = stack.enter_context(os.fdopen(fd, "w"))
            token = source.read().rstrip("\r\n") if source is not None else None
            result = APIKeys(store).create(
                user_id,
                name,
                token=token,
                views=view,
                admin=admin,
                expires_in=expires_in,
            )
            secret = result.pop("token")
            if stream is not None:
                stream.write(secret + "\n")
            click.echo(json.dumps(result))
        except (ValueError, OSError) as exc:
            raise click.ClickException(str(exc)) from None


@keys.command("list")
@click.argument("user_id")
@click.pass_obj
def list_keys(directory, user_id):
    """List this owner's key IDs and grants, never key values or digests."""
    store = UserStore(directory)
    try:
        click.echo(json.dumps(APIKeys(store).list(user_id), indent=2))
    finally:
        store.close()


@keys.command("revoke")
@click.argument("user_id")
@click.argument("key_id")
@click.pass_obj
def revoke(directory, user_id, key_id):
    """Permanently revoke a key and its grants without restarting the service."""
    store = UserStore(directory)
    try:
        APIKeys(store).revoke(user_id, key_id)
        click.echo("API key revoked")
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        store.close()
