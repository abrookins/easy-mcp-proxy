# Remote configuration, live updates, and user isolation

Agent-plan: `c2f83bf9`

This is the original delivery brief. Implementation is recorded in
[ADR-010](../decisions/010-user-owned-configuration.md); current commands and
operational limits are in the [administration guide](../user-owned-configuration.md).
The [acceptance record](remote-configuration-acceptance.md) distinguishes completed
local work from pending production/client checks. Requirements below are not a
claim that every release gate has passed.

## Required outcome

All proxy configuration and views belong to the current logged-in OAuth user.
Every request resolves that user's configuration from verified identity. There is
no global operational configuration or fallback to another user's configuration.

Andrew can edit a view from his phone, preview and apply the change while a tool
call runs, and continue using connected clients without logging in again.

The user subsequently authorized branch implementation and, on 2026-10-15,
switching the running installation to this branch. See the acceptance record for
that deployment. Agent-plan contains task state; this brief defines requirements.

## Identity is the configuration boundary

Resolve the verified OAuth issuer and subject to an internal user ID. Do not use
email, OAuth client ID, a URL user parameter, or a model argument as the ownership
key. Claude and ChatGPT signed in as the same person see that person's config,
subject to any narrower client grants.

`/mcp` selects the authenticated user's default view. `/view/<name>/mcp` selects
that name inside the authenticated user's views. `/search/mcp`, `/views`,
instructions, tool discovery, resources, and management operations use the same
identity boundary. Two users can define the same server and view names without
collision. A missing identity or view never falls back to installation-global
tools. Root health checks may remain anonymous but must reveal no user config.

The configuration store may be one physical database, but every operational
record and lookup is user-scoped. Servers, views, secret references, revisions,
upstream credentials and connections, runtime generations, cached outputs, and
audit records carry user ownership. A global in-memory registry must not leak one
user's tools, instructions, schemas, or resources to another authenticated user.

Only deployment settings remain service-wide: listener address, database location,
OAuth provider bootstrap, signing-key references, and host execution policy.
Do not add a shared workspace abstraction that weakens this direct user ownership.
The initial installation admits one person; no signup or team-management UI is
needed. Use two synthetic OAuth users in tests to prove the architecture.

API keys are explicitly bound by a local operator to a provisioned OAuth owner,
with separate client/view grants, hashed storage, optional expiry and permanent
revocation. They never infer ownership from the first login or legacy environment.
Local CLI and stdio require explicit owner/grant provisioning as well.
If retained, bind each to a provisioned user and grant. No implicit default-owner
mapping for remote requests. Existing global YAML requires an explicit owner at
migration; an arbitrary first login must not claim its credentials.

The central security scenario is an admission-policy mistake: another person
successfully authenticates with a valid OAuth identity because an allowlist or
provider setting is too broad. That identity receives no access to Andrew's
configuration, tools, credentials, caches, or administration privileges. Return
an unprovisioned/denied result, or an empty account if explicitly designed; never
attach existing data or copy credential-bearing defaults on login. Ownership
authorization must hold independently of the admission allowlist. This does not
claim protection if token verification itself is compromised or an attacker can
forge Andrew's verified identity.

## Milestones

| Milestone | Observable result |
| --- | --- |
| M0: Baseline and design | Reproduce failures and define identity, persistence, and activation contracts. |
| M1: Durable authentication | Restart preserves valid authorization and refresh capability. |
| M2: User-owned runtime | All views, discovery, execution, and stored config resolve by OAuth user. |
| M3: Live administration | Browser and CLI share a revisioned management service with live apply. |
| M4: Core release | Mobile-browser workflow, isolation, migration, and rollback evidence pass. |
| M5: Embedded administration | Portable MCP Apps management screens work on verified hosts with browser fallback. |
| Optional extension | Forward upstream MCP Apps only after a separate scope decision. |

## Pre-implementation evidence and compatibility constraints

- `mcp_proxy/web_ui.py` already provides `/config`, JSON GET/PUT operations,
  override-file persistence, and a restart operation that sends `SIGHUP`.
- Save handlers do not fully validate the resulting `ProxyConfig` and references.
- `MCPProxy.http_app()` constructs view mounts and registers tools at startup.
  `ToolRegistry` supports snapshot replacement; metadata replacement alone does
  not provide atomic runtime activation or per-request user isolation.
- `ClientManager` uses server-name keys and shared upstream clients. Those keys
  and all related runtime/caching paths need user ownership.
- Local FastMCP already defaults to encrypted OAuth disk storage and derives
  signing material from the client secret. Deployment behavior remains unverified.
- The browser session-secret fallback generates a new secret on each invocation
  without an Auth0 secret. Use dedicated persistent browser signing material.
- Preserve `/mcp` as the user's default view and `/view/remote/mcp` as that user's
  restricted view. Do not silently remap one endpoint to the other.
- Related plan `1ff53bcd` records OAuth resource-binding experiments and rollbacks.
  Reconcile that history with deployed code. Preserve working root discovery,
  dynamic registration, and Claude flows until replacement behavior is proven.
- Preserve supported stdio behavior, search exposure modes, parameter transforms,
  custom tools, hooks, compositions, and bounded output handling.
- Preserve unrelated working-tree changes and the existing security plan.

## Architecture and persistence

One management service serves browser routes, remote CLI, and MCP admin tools.
It owns user-scoped reads, edits, validation, revisions, preview, apply, rollback,
and audit events. Adapters must not implement separate mutation semantics.

SQLite and one active runtime process are the proposed initial deployment.
Confirm that choice in an ADR after deployment inventory. Keep YAML for explicit
bootstrap, import, and export. Define deletion and environment substitution;
avoid two authoritative writable stores and silent file-watcher overwrites.

Separate stable HTTP/OAuth serving from user-owned runtime generations. Every
call uses one generation consistently. Prepare new upstream connections before
switching new calls; drain old clients with a bounded deadline. Respect async
context-manager task ownership and cancellation when replacing subprocess clients.
Unchanged upstreams retain their connections and process IDs. One user's update
must not disconnect another user's sessions or publish their tool metadata.

Persist desired and active revision state separately. Specify recovery at each
failure boundary between database commit and runtime activation. An ambiguous
timeout is recoverable through an operation ID and status query. SQLite
transactions alone cannot make an in-memory generation swap crash-atomic.

## Authorization and secrets

Ordinary tool access does not confer configuration administration. Enforce grants
in the management service and every invocation path, including direct wrappers,
search helpers, custom tools, hooks, and compositions. Hiding tools is insufficient.
Treat changes to commands, environment, filesystem paths, and Python hooks as
privileged host operations; user ownership does not sandbox arbitrary subprocesses.

Only explicitly provisioned operators may register host commands, Python hooks,
filesystem access, or references to host environment secrets. An accidentally
admitted identity must not gain these privileges by owning an empty account or by
administering its own configuration. Restrict subprocess environment inheritance
and secret-provider lookups so user config cannot enumerate or reuse the service's
global credentials. Restrict user-configurable HTTP destinations where they could
reach privileged local/internal services. Reject these operations until owner and
host permissions are explicit; do not rely on UI hiding.

Secrets use scoped references and write-only input. Redact values from config
reads, exports, revisions, logs, previews, MCP output, and UI resources. Preserve
encryption and key-rotation behavior when changing OAuth storage. Grant revocation
must reject subsequent calls immediately; specify what happens to in-flight calls.
Rollback must not resurrect revoked credentials or bypass current policy.

## Configuration contract

Each revision records user, schema version, base revision, actor, timestamp,
redacted diff, and activation status. Every mutation supplies its expected base
revision. Stale updates fail without overwriting another edit.

Preview validates models, references, grants, exposed names, transforms, and
runtime support. It reports affected upstreams and added/removed/changed tools,
plus restart-required settings. Structural validation must not execute arbitrary
hooks or commands. Explicit connection probes may start authorized upstreams.

Apply binds to the reviewed revision, rechecks authority, prepares changed
resources, switches routing, and records the result. Failures retain a usable
known revision. Rollback creates and validates a new revision through the same path.

| Change | Intended behavior |
| --- | --- |
| Description, alias, parameter binding, view filter | Update dispatch and metadata without upstream reconnects. |
| Add/change upstream | Prepare replacement; switch affected routes; drain retired client. |
| Add/remove view | Update user-specific routing without recreating unrelated sessions. |
| Remove tool/upstream | Reject new calls after activation; follow explicit in-flight policy. |
| Revoke grant/credential | Reject subsequent calls; do not wait for discovery refresh. |
| Listener, deployment, unsupported code changes | Report restart requirement; never imply live support. |

Notify supported clients of tool-list changes. Document manual refresh where
required. Separate server activation from host tool discovery and from the model's
existing conversation context. Keep search helper contracts stable where possible.

## Authentication and restart behavior

Diagnose deployed FastMCP version, persistence directory, service account, key
stability, resource identifiers, and refresh behavior before attributing the
reported login loss to in-memory storage. Separate transport reconnection from
interactive OAuth authorization. Test valid access and refresh across a real
process restart, alongside expiry, logout, and revocation.

Browser sessions carry the verified user identity. Validate OAuth state, callback
identity, admission policy, return URLs, and refresh/logout semantics. Use secure
cookies and CSRF/origin protection for writes. Remove state-changing GET routes.
Do not issue an unrestricted admin session merely because token exchange succeeds.

## Interfaces

Build on `/config` with a phone-friendly server list, connection tests, view/tool
editor, revision diff, impact preview, Apply, operation status, and rollback.
Show the signed-in identity and active revision. Host the UI in this service;
a separate frontend deployment is unnecessary. Test touch, keyboard, accessibility,
expired sessions, conflicts, failures, and narrow-screen layouts.

The HTTP API and remote CLI expose the same scoped management operations,
structured errors, concurrency tokens, and idempotency. Define secure CLI
credential sourcing and remote OAuth login/refresh. Legacy local edits either
explicitly import into a named owner or receive clear migration guidance.

MCP admin tools use bounded typed operations. Preview and apply are separate;
apply is bound to the reviewed revision and impact. Resolve the owner from OAuth,
never a model-supplied identity. Admin tools remain usable without embedded UI.

MCP Apps later adds selected screens through standard UI resources and the host
bridge. Use capability detection, text results, and a browser link. Share UI
components where practical, with adapters for browser HTTP and host tool calls.
Keep secrets out of model context and bundles; sensitive credential entry can
remain in the authenticated browser.

## Client support and optional upstream forwarding

As inspected on 2026-10-13, Claude documents interactive connectors on web,
desktop, iOS, and Android. OpenAI documents MCP Apps UI, while its custom-app help
article describes mobile availability as web only. Recheck private custom-app
support on actual accounts/devices before promising parity. Unsupported surfaces
must be reported as unavailable, never as passed or as a failed core milestone.

- [MCP Apps overview](https://apps.extensions.modelcontextprotocol.io/api/documents/overview.html)
- [Claude interactive connectors](https://support.claude.com/en/articles/13454812-use-interactive-connectors-in-claude)
- [OpenAI MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- [ChatGPT custom apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- [MCP notifications](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/servers/notifications.md)

Serving this proxy's admin app is distinct from forwarding upstream Apps. Optional
forwarding needs UI metadata preservation, namespaced resources, tool-name mapping,
result metadata fidelity, authorization, and search-mode compatibility. Keep it
outside core release and choose proceed/defer after the embedded admin milestone.

## Acceptance and release evidence

Each implementation task includes focused regression tests. Run `make check` and
`make test`; retain the repository's 100% branch-aware coverage requirement.

1. Two OAuth users configure identically named views and upstreams. Each sees and
   executes only their own definitions through every endpoint and helper.
2. Missing identity, unknown user/view, spoofed user parameters, changed bearer
   identity on an existing session, and guessed cache/resource IDs cannot cross
   owners or expose global tools. Bind or reject session identity changes safely.
3. A phone browser edits/previews/applies a view while an unrelated long call
   completes. Unchanged upstream connections and other users' sessions survive.
4. Malformed config, failed probes, stale edits, cancellation, and activation-time
   crashes leave recoverable state and truthful revision/operation status.
5. OAuth access and refresh survive restart on the real service configuration;
   expiry, logout, and revocation still work.
6. Migration assigns legacy config to an explicit user, preserves effective tools
   and endpoints, backs up state, and supports a rehearsed reverse migration.
7. Claude and ChatGPT acceptance records include versions, account restrictions,
   refresh requirements, and mobile availability. Browser mobile is the baseline.
8. Logs, diffs, tool results, UI resources, and exports contain no raw secrets.
9. Deliberately broaden the OAuth admission allowlist and log in as a second valid
   subject. It cannot discover or call Andrew's tools, read his config/cache, claim
   migrated data, acquire admin rights, reference host secrets, or launch a command
   or hook to bypass ownership. Test this independently of admission checks.

Record activation time, desired/active revision, upstream health, draining calls,
operation failures, and auth recovery without token contents. Bound diagnostic
payloads and retention. Coordinate admin-route exposure with security plan
`1ff53bcd`; do not broaden public routes as an incidental implementation change.

## Resuming work

Run `~/bin/agent-plan get c2f83bf9`. Update task status through the CLI. Dependencies
control readiness; order supplies priority. Optional upstream forwarding does not
block the core release. Record unresolved live-environment checks explicitly.
