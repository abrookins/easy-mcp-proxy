"""Pure config validation, opaque secret references and host capability policy."""

import copy
import json
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from mcp_proxy.identity import Principal
from mcp_proxy.models import ProxyConfig
from mcp_proxy.user_store import UserStore

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SECRET = "$secret"


def _secret_path(path: tuple[str, ...]) -> bool:
    # Match schema locations, not names: a view named "default" is not a
    # parameter default, and a view named "env" is not a subprocess environment.
    return bool(
        re.search(
            r"^(cache_secret$|mcp_servers/[^/]+/(env|headers|args)(/|$))"
            r"|/parameters/[^/]+/default(/|$)"
            r"|^tool_views/[^/]+/composite_tools/[^/]+/parallel/[^/]+/args(/|$)",
            "/".join(path),
        )
    )


def seal_config(store: UserStore, principal: Principal, value, path=()):
    """Move sensitive leaf values to owner-scoped encrypted secret storage."""
    if isinstance(value, dict):
        if SECRET in value:
            if set(value) != {SECRET} or not isinstance(value[SECRET], str):
                raise ValueError("Invalid secret reference")
            store.get_secret(principal, value[SECRET])
            return value.copy()
        return {
            k: seal_config(store, principal, v, (*path, k)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [seal_config(store, principal, v, path) for v in value]
    if _secret_path(path) and value is not None:
        return {SECRET: store.put_secret(principal, value)}
    return value


def materialize_config(store: UserStore, principal: Principal, value):
    """Resolve references only within this caller's namespace."""
    if isinstance(value, dict):
        if SECRET in value:
            if set(value) != {SECRET} or not isinstance(value[SECRET], str):
                raise ValueError("Invalid secret reference")
            return store.get_secret(principal, value[SECRET])
        return {k: materialize_config(store, principal, v) for k, v in value.items()}
    if isinstance(value, list):
        return [materialize_config(store, principal, v) for v in value]
    return value


def _host_capabilities(config: ProxyConfig) -> dict:
    """Changes to executable code or destinations require installation privilege."""
    servers = {
        name: server.model_dump(exclude={"tools", "cache_outputs"})
        for name, server in config.mcp_servers.items()
    }
    views = {
        name: {"hooks": view.hooks, "custom_tools": view.custom_tools}
        for name, view in config.tool_views.items()
        if view.hooks or view.custom_tools
    }
    return {"servers": servers, "code": views}


def validate_managed_config(
    store: UserStore, principal: Principal, raw: dict, previous: dict
) -> ProxyConfig:
    """Validate without constructing proxies, importing hooks or executing probes."""
    store.authorize(principal, admin=True)
    candidate = materialize_config(store, principal, raw)
    old = materialize_config(store, principal, previous)
    try:
        config = ProxyConfig.model_validate(candidate, extra="forbid")
        before = ProxyConfig.model_validate(old)
    except ValidationError:
        # Pydantic errors can include secret input values.
        raise ValueError("Invalid configuration structure") from None
    if _host_capabilities(config) != _host_capabilities(before):
        store.authorize(principal, admin=True, operator=True)
    for name, server in config.mcp_servers.items():
        if not NAME.fullmatch(name):
            raise ValueError("Invalid server name")
        if bool(server.command) == bool(server.url):
            raise ValueError("Each upstream requires exactly one command or URL")
        if server.url:
            url = urlsplit(server.url)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("Use an HTTP URL without credentials or query")
    for name, view in config.tool_views.items():
        if not NAME.fullmatch(name) or name in {"_search", "search", "admin"}:
            raise ValueError("Invalid or reserved view name")
        if view.exposure_mode not in {"direct", "search", "search_per_server"}:
            raise ValueError("Invalid exposure mode")
        if set(view.tools) - set(config.mcp_servers):
            raise ValueError("View references an unknown upstream")
        if set(view.exclude_servers) - set(config.mcp_servers):
            raise ValueError("View excludes an unknown upstream")
    if config.cache_base_url or config.cache_secret:
        raise ValueError("Cache routing and signing are managed by the service")
    _reject_environment_references(candidate)
    return config


def _reject_environment_references(value):
    if isinstance(value, str) and "${" in value:
        raise ValueError("Host environment interpolation is not allowed")
    if isinstance(value, dict):
        for item in value.values():
            _reject_environment_references(item)
    if isinstance(value, list):
        for item in value:
            _reject_environment_references(item)


def config_impact(previous: dict, candidate: dict) -> dict:
    """Return redacted structural changes without exposing any config values."""
    changes = {}
    for section in ("mcp_servers", "tool_views"):
        old, new = previous.get(section, {}), candidate.get(section, {})
        changes[section] = {
            "added": sorted(new.keys() - old.keys()),
            "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
        }
    changes["restart_required"] = False
    fields = []

    def compare(before, after, path=()):
        if before == after:
            return
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(before.keys() | after.keys()):
                compare(before.get(key), after.get(key), (*path, key))
        elif len(fields) < 200:
            # Payloads are already sealed; never materialize credentials here.
            fields.append({"path": list(path), "before": before, "after": after})

    compare(previous, candidate)
    changes["fields"] = fields
    changes["field_limit"] = 200
    old_servers = previous.get("mcp_servers", {})
    new_servers = candidate.get("mcp_servers", {})
    changes["upstream_replacements"] = sorted(
        name
        for name in old_servers.keys() & new_servers.keys()
        if {
            k: v
            for k, v in old_servers[name].items()
            if k not in {"tools", "cache_outputs"}
        }
        != {
            k: v
            for k, v in new_servers[name].items()
            if k not in {"tools", "cache_outputs"}
        }
    )
    changes["tool_catalog"] = (
        "Revalidated during apply; refresh host discovery afterward"
    )
    return changes


class ConfigService:
    """Shared user-scoped preview/read operations for HTTP, CLI and MCP."""

    def __init__(self, store: UserStore):
        self.store = store

    def read(self, principal: Principal) -> dict:
        self.store.authorize(principal, admin=True)
        revision, config = self.store.active(principal)
        return {"revision": revision, "config": copy.deepcopy(config)}

    def preview(self, principal: Principal, base: str | None, config: dict) -> dict:
        if len(json.dumps(config).encode()) > 1_048_576:
            raise ValueError("Configuration exceeds the 1 MiB limit")
        current, previous = self.store.active(principal)
        # Check before creating secret records as well as inside the transaction.
        if current != base:
            from mcp_proxy.user_store import Conflict

            raise Conflict("Configuration changed; read the latest revision")
        validated = validate_managed_config(self.store, principal, config, previous)
        # Preserve existing opaque references; do not serialize resolved credentials.
        sealed = seal_config(self.store, principal, config)
        revision = self.store.draft(principal, base, sealed)
        return {
            "revision": revision,
            "base": base,
            "impact": config_impact(previous, sealed),
            "views": sorted(validated.tool_views),
            "validation": {
                "structure": "passed",
                "upstream_discovery": "checked during probe and apply",
                "host_execution": "not started by preview",
            },
        }

    def rollback_preview(self, principal: Principal, base: str, target: str) -> dict:
        self.store.authorize(principal, admin=True)
        config = self.store.revision(principal, target)["config"]
        return self.preview(principal, base, config)
