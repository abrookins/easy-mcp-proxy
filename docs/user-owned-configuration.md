# User-owned configuration and live administration

The managed service reads configuration from its encrypted user store. It never
falls back to `config.yaml`, overrides, a global view, or the first person to log
in. OAuth admission and ownership are separate checks. An admitted but
unprovisioned person can inspect their own verified identity, but receives no
tools, configuration, credentials, or administration access.

This is an upgrade of the **serve command**, including stdio. The low-level
`MCPProxy(config)` library and legacy file-editing commands remain available for
local tooling; they are not the managed HTTP service. Existing unauthenticated
HTTP and static API tokens are not supported by the managed gateway. Remote
clients must use OAuth. Do not point an old global HTTP deployment at the new
branch without completing the migration below.

## Bootstrap and grants

Service settings are `MCP_PROXY_STATE_DIR`, the existing
`FASTMCP_SERVER_AUTH_AUTH0_*` provider settings, `MCP_PROXY_HOST` (defaults to
loopback), and the serve port. Keep the public Auth0 base URL unchanged. Use a
root origin such as `https://proxy.example.org`, without a path prefix. One
runtime process is supported; the state directory's advisory lock rejects a
second HTTP/stdio runtime or an offline import while serving.

The state directory must be mode 0700. Key files are mode 0600. The service
creates independent `oauth.key`, `browser.key`, and `config.key` files and
initialization markers. Missing or corrupt initialized keys fail closed; restore
them, do not delete state until the service starts. Back up keys separately from
routine database exports, and protect both backups.

Only a local operator can provision users and grants:

```sh
export MCP_PROXY_STATE_DIR="$HOME/.local/state/easy-mcp-proxy"
uv run mcp-proxy users provision --issuer 'https://YOUR-ISSUER/' \
  --subject 'VERIFIED-SUBJECT' --operator
# Record the returned internal user ID. Repeat provisioning does not elevate it.
uv run mcp-proxy users grant USER_ID --client mcp-proxy-browser --admin --view '*'
uv run mcp-proxy users grant USER_ID --client mcp-proxy-local --admin --view '*'
```

Use the verified issuer and subject, not an email or an application ID. For a new
remote CLI application, first run `mcp-proxy manage --url PUBLIC_ORIGIN identity`.
It performs OAuth and prints only the verified issuer, subject, and **downstream**
client ID. The operator grants that client ID explicitly. Calling `identity`
does not provision an account. Persisted CLI OAuth credentials are encrypted under
`~/.local/state/mcp-proxy-client`, overridable with `--credential-dir`.

Grant runtime applications only the views they need:

```sh
uv run mcp-proxy users grant USER_ID --client REGISTERED_CLIENT_ID --view remote
# A separate connector for administration:
uv run mcp-proxy users grant USER_ID --client ADMIN_CLIENT_ID --admin --view admin
uv run mcp-proxy users revoke USER_ID --client REGISTERED_CLIENT_ID
```

An admin grant does not grant a view automatically; specify both. Grant changes
are checked on every discovery/execution/management request. Revoke also deletes
that application's browser sessions. Existing calls may finish. Operator status
is an additional, locally provisioned privilege: changing commands, environments,
working directories, HTTP destinations, hooks, or Python custom tools requires
it. Nonoperators cannot register even a public HTTP destination. This conservative
policy prevents local-network and metadata-server access through administration.
Trusted operator code runs with the service OS account and is **not sandboxed**.

## Migrate an existing installation

Rehearse on isolated state first. No production service has been changed by this
branch. Record the old executable/commit, FastMCP version, public origin, service
manager configuration, YAML and `.overrides.json`, OAuth storage location, and
provider settings. Stop the old service before copying its mutable OAuth state.
Make a private backup of all those files and verify the backup can be read.

For FastMCP v3 default encrypted FileTree storage compatible with the installed
SDK, the OAuth directory is typically `~/.fastmcp/oauth-proxy/FINGERPRINT`.
Confirm the actual deployment's directory; do not guess from another checkout.
Set the **existing** Auth0 client secret in the environment, never on a command
line. Import OAuth state before starting the managed service:

```sh
uv run mcp-proxy users import-oauth --source /PRIVATE/PATH/FINGERPRINT
uv run mcp-proxy users import-oauth --source /PRIVATE/PATH/FINGERPRINT --apply
```

The first command is a dry run. The import checks the key fingerprint, refuses
existing target OAuth state and symlinks, copies encrypted records and expiration
metadata, rebases FileTree collection paths, and preserves the old signing key.
The original state is untouched. Unsupported storage formats require a separately
verified migration; do not assume this command handles older SDKs or custom
storage. An interrupted import fails closed. Remove only its incomplete target
copy after verifying the source/backup, then retry with the runtime stopped.

Provision the explicit owner and local/browser grants, then import effective YAML:

```sh
uv run mcp-proxy users import --issuer 'https://YOUR-ISSUER/' \
  --subject 'VERIFIED-SUBJECT' --config /PRIVATE/PATH/config.yaml
uv run mcp-proxy users import --issuer 'https://YOUR-ISSUER/' \
  --subject 'VERIFIED-SUBJECT' --config /PRIVATE/PATH/config.yaml --apply
```

Import merges the existing overrides and resolves environment substitutions using
the legacy loader. It reports a source checksum, encrypts credential-bearing
values, retains prior committed revisions, and leaves source files untouched.
Repeated effective imports return `unchanged`. No login can claim those files.
Old cache signing/base-URL settings are replaced by managed per-user/view values;
old cache links do not migrate. Import validates configuration but does not start
upstreams. Startup/first use and an explicit probe verify their availability.

Start with `uv run mcp-proxy serve --transport http --port 8000`. Passing
`serve --config` fails with migration guidance. The user store is now authoritative;
editing YAML or overrides has no effect on the managed service. Existing local
`server`, `view`, `config`, and inspection commands still operate on legacy files.
Use `manage` or `/config` for live changes.

Preserve existing client registrations through the OAuth import, then explicitly
grant each retained client ID its intended views. Test access and refresh before
retiring the backup. A deployment with a different OAuth implementation or an
expired/revoked upstream credential may still need a fresh authorization.

## Browser, API, CLI, and MCP

Open `/config` in a browser. Login uses the proxy's OAuth authorization code flow,
PKCE, a single-use expiring state record, and the verified OAuth identity. Sessions
last 24 hours, survive restart, and are revocable. HTTPS cookies are secure and
HTTP-only. Cookie-authenticated writes require the exact configured Origin;
logout is POST-only. The page uses a restrictive CSP and no external frontend host.

The browser supports upstream connection edits, view creation/exposure modes,
an advanced JSON editor, preview, probe, apply, history, and rollback previews.
Existing credentials appear as `{"$secret":"opaque-id"}`. Preserve that object
when editing. Replace it with a new value in the browser to rotate the credential.
Use `env`, `headers`, `args`, or parameter defaults for credentials, never tool
descriptions or names. New remote config cannot interpolate `${HOST_ENV}`.
Removing a field removes it from the next generation; it does not rewrite history.

HTTP management operations are:

| Method and path suffix under `/config/api/` | Body / result |
| --- | --- |
| GET `identity` | Verified bearer identity; no grant/provisioning side effect |
| GET `config` | Current revision and config with opaque secret references |
| GET `history` | Last 100 revision metadata records |
| GET `status` | Identity, durable/runtime revisions, upstreams, calls, audit events |
| POST `preview` | `{base, config}` → immutable candidate ID and structural impact |
| POST `probe` | `{revision, server}` → temporary connection result/tool count |
| POST `apply` | `{revision}` → committed state; retries are idempotent |
| POST `rollback` | `{base, target}` → new candidate under current policy |

Responses use 401/403 for authentication/authorization, 400 for invalid input,
404 for scoped missing records, 409 for revision conflicts, 413 for an oversized
HTTP body, and 502 for preparation failures. HTTP config bodies are capped at
1 MiB. Error responses do not include raw upstream exceptions or credential values.
A preview is structural; upstream discovery, schemas, collisions, and availability
are finalized during preparation. An unsuccessful apply leaves the active revision
unchanged. Use the operation's revision ID to reconcile an interrupted response.

The CLI exposes the same operations:

```sh
uv run mcp-proxy manage --url https://proxy.example.org config
uv run mcp-proxy manage --url https://proxy.example.org preview --input candidate.json
uv run mcp-proxy manage --url https://proxy.example.org apply --input apply.json
```

`candidate.json` contains `{ "base": "CURRENT_REVISION", "config": {...} }`;
use `null` for an empty account. `apply.json` contains only
`{ "revision": "REVIEWED_CANDIDATE" }`. `--input -` reads stdin. OAuth is the
normal credential source; automation may provide a current OAuth bearer through
`MCP_PROXY_ACCESS_TOKEN`. No token or secret command-line flags are provided.
Only HTTPS or loopback HTTP is accepted. Read-only operations reject `--input`.

Runtime endpoints remain `/mcp`, `/view/NAME/mcp`, and `/search/mcp`. `/views`
returns only granted views. Root OAuth discovery and registration are preserved,
and named endpoints challenge using the root `/mcp` resource metadata. Each
stateless HTTP request resolves its authenticated owner; there is no shared
transport session that can carry another user's identity. Clients must keep sending
OAuth credentials. A lost TCP/MCP request is separate from a lost OAuth login.

The dedicated `/view/admin/mcp` connector exposes `proxy_config`, `proxy_status`,
`proxy_history`, `proxy_preview`, `proxy_probe`, `proxy_apply`, and `proxy_rollback`.
It requires an admin grant **and** access to `admin`. Normal view endpoints do not
list these tools. MCP config payloads/results are bounded to 64 KiB; larger configs
use the browser/CLI. MCP rejects inline secrets; credential entry remains in the
browser. All ownership derives from verified context, never a tool argument.

`proxy_status` advertises `ui://mcp-proxy/admin-v1.html`, MIME
`text/html;profile=mcp-app`, using `_meta.ui.resourceUri`. The bundled standard
MCP Apps SDK communicates through the host bridge. No vendor-only API is required.
Resource access rechecks the admin endpoint and grant. The resource requests no
external connect/resource domains or extra permissions. Without UI support, text
tools and the returned `browser_url` remain usable. The embedded and browser
screens share components and invoke the same config/runtime service.

## Live-change behavior

All user configuration fields can be prepared as a new generation. View filters,
aliases, descriptions, parameters, cache policy, and compositions reuse unchanged
upstream workers. Connection target/credential changes prepare replacements first.
Operator hooks/custom tools are loaded during preparation, never during preview.
Conflicting exposed tool names fail preparation; explicitly alias/filter collisions.
A removed view fails on subsequent calls; no route or owner fallback is used.

The default drain deadline is 10 seconds. Existing calls pin their original
generation; retired connections close once those calls finish or the deadline
expires. A call exceeding that deadline may fail. New calls use the new generation.
One user's updates do not rebuild another user's workers. Probes always close their
temporary clients. Unreachable upstreams, cancellation, and failed commits do not
publish a partial runtime. Startup abandons interrupted `preparing` operations and
rebuilds the durable committed revision lazily.

MCP apply sends `notifications/tools/list_changed` on its active requesting stream.
Stateless HTTP has no persistent stream to broadcast a browser edit to idle clients.
Hosts that cache tools must refresh their connector/tool list; some may require
reconnecting transport. This does not inherently require a new OAuth authorization.
Do not promise automatic discovery refresh in every Claude/ChatGPT client.

Bootstrap changes (listener, public origin, OAuth provider, state location, host
policy/code deployment) still require an operator restart. Custom Python code
changes are not hot-reloaded merely by reapplying the same module path.

Trusted stdio requires `MCP_PROXY_STATE_DIR`, `MCP_PROXY_OWNER_ISSUER`, and
`MCP_PROXY_OWNER_SUBJECT`, plus an explicit `mcp-proxy-local` grant. It selects
that user's store without a YAML fallback. It cannot run concurrently against the
same state directory as the HTTP runtime.

## Backup, restore, rotation, and rollback

Stop the sole runtime before taking a filesystem snapshot. Copy `users.sqlite3`,
all three keys and initialization markers, and the entire `oauth/` directory into
private storage. Preserve the public origin and Auth0 settings in the deployment
backup. Retain the legacy YAML/overrides and old executable for release rollback.
Do not put decrypted exports or keys into git, logs, or a plan record.

Restore the full snapshot to the **same absolute state path** while stopped.
FileTree metadata contains absolute paths. Restore permissions (0700 directories,
0600 keys/database), start one process, check `/health`, verify the expected
revision, exercise a granted view, and verify OAuth refresh and browser login.
A same-path restore preserves encrypted references and token lookup mappings.
Restoring just the database without `config.key` cannot decrypt configuration.

In-app rollback previews a retained revision and applies it as a new revision.
It cannot restore revoked grants or deleted secret records and cannot bypass the
current operator policy. Release rollback instead stops the managed service,
restores the old executable/config/provider state from the pre-upgrade snapshot,
and restarts the old service. No migration rewrites the original YAML.

Signing-key rotation intentionally invalidates old proxy tokens. Browser-key
rotation invalidates browser cookies. Config-key rotation requires decrypting and
reencrypting both revision and secret payloads in a controlled offline migration;
there is no automatic rotation command. Restore matching keys if a rotation was
accidental. Do not generate a new key over unreadable state.

Retain at most 100 recent revisions plus the current active/preparing records,
and 1000 audit events per user (status returns the latest 100). Secrets referenced
by history are retained until explicit local revocation; deleting a reference
invalidates new execution and rollback that requires it. Orphan secret/OAuth-file
compaction is not automatic. Include disk usage in installation maintenance;
never delete ciphertext records without a verified backup and reference audit.

## Diagnostics and acceptance

Compare `desired_revision` with `runtime_revision`: an unloaded user runtime has
no runtime revision until first use; a preparation failure keeps the prior active
revision. History distinguishes `draft`, `preparing`, `active`, `failed`, and
`interrupted` recovery errors. Historical committed rows remain `active` in
history; the user's current pointer identifies which one is serving. Retrying an
older committed apply returns `superseded` and never reactivates it. To reactivate,
create a rollback preview.

An unchanged revision with old host tools usually indicates a client discovery
cache. An HTTP 401 on MCP may instead indicate missing/expired OAuth or revoked
user/view access. A fresh OAuth login with 403 on config means no admin grant;
it does not mean the proxy lost the user's config. Keep `proxy_status`, the local
process restart tests, and actual client refresh observations distinct.

See [acceptance evidence](specs/remote-configuration-acceptance.md) for commands,
local results, device limitations, and release gates. Automated mobile viewport
coverage is not a claim of testing iOS/Android native applications.

The legacy browser cookie format is not imported. Existing browser administrators
log in once after this upgrade; managed browser sessions then survive subsequent
restarts. Existing MCP OAuth tokens are preserved only by the compatible explicit
OAuth-state import, not by generating a fresh state directory.
