# 010: User-owned configuration and live activation

Status: implemented and deployed from `feat/user-owned-live-configuration` on
2026-10-15. Auth0-backed restart checks passed; actual client/device acceptance
remains pending. See the
[acceptance record](../specs/remote-configuration-acceptance.md).

## Decision

The service resolves verified `(issuer, subject)` to an explicitly provisioned
internal user. Login never provisions ownership. Admission restrictions remain
useful but are independent of authorization. Unknown identities fail closed.
OAuth client IDs identify applications, not people. Explicit local provisioning
creates grants; remote management cannot create users or elevate host privileges.

Use a SQLite store in a private state directory with schema versioning and foreign
keys. Every configuration, revision, secret, operation and grant is keyed by user.
Use encrypted revision payloads as well as encrypted secret storage so hidden
parameter defaults and imported legacy credentials are not stored in plaintext.
Redacted API payloads preserve opaque secret references on subsequent edits.
The master key and OAuth signing material live outside database backups.

The initial deployment has one writer/runtime process. SQLite uses explicit
transactions and expected-revision comparisons. Multiple HTTP workers are not
supported until generation and notification coordination is implemented.

## Interfaces

- Identity resolution accepts only claims produced by the configured verifier.
  The stable issuer and subject are required. Missing values never select a default.
- A request context carries user, OAuth application and selected view. All grants
  are resolved from the store at execution time so revocation affects new calls.
- The management service accepts this context, an expected revision and a config.
  Preview returns a persisted immutable candidate and impact. Apply takes the
  candidate ID, not an independently editable replacement payload.
- A runtime manager owns generations by user. Each generation owns an MCPProxy
  built from only that user's config, with one registry per view. A dynamic
  FastMCP provider selects components from the current generation for each request.
- Calls acquire a generation lease before executing. Tools from a retired
  generation cannot be invoked as new calls. Existing calls finish against the
  pinned generation; revocation rejects subsequent calls immediately.
- Upstream connection workers own their async context for their entire lifetime.
  Generations share unchanged worker references within the same user. Release
  drains and closes only resources no longer referenced by any active call.

## Activation state machine

Preview creates `draft(base, candidate)`. Apply checks authority and base revision,
then records `preparing`. Upstreams connect and registries build before activation.
Preparation failures record `failed` without changing active state. Once ready,
commit the new durable active revision and immediately publish the generation
without an intervening await. Retire old generation references after publication.

A crash before commit retains the old revision. A crash after commit starts from
the newly committed revision. Startup marks interrupted preparation as
`interrupted` and rebuilds the committed generation. A durable revision is authoritative on restart;
runtime availability and preparation failure are reported separately. Database
transactions do not cover external resources, so orphan cleanup and startup
reconciliation are required. Repeated apply of the same operation returns its
existing outcome; a conflicting operation cannot silently overwrite a newer base.

Rollback previews a historical payload as a new candidate. Current host policy,
grant checks and secret validity still apply. Rollback cannot restore user/grant
provisioning or credential revocations.

## HTTP, browser and OAuth

Keep one authorization server and stable HTTP transport layer. Resolve the view
from the path and the owner from authentication. Default, named, search, resource,
cache and management routes all use that boundary. Existing `/mcp` and
`/view/remote/mcp` semantics remain distinct within each user.

Use stable encrypted OAuth persistence and an independent browser session key.
The browser login requires nonce/state binding and verified identity; it cannot
derive ownership from unverified token-response fields. Browser writes require
same-origin CSRF protection. All management mutations require config-admin grants.
Host commands, hooks, and all new HTTP destinations additionally require locally
provisioned operator privilege. Remote config rejects host environment
interpolation; offline import resolves it before storing encrypted values.

The private configuration migration specifies the owner's issuer and subject.
No first-login claim, global operational fallback, or shared credential defaults
are permitted. Trusted local stdio requires an explicitly provisioned
issuer/subject and a `mcp-proxy-local` grant. API keys require explicit local
binding to a provisioned owner and independent client/view grants. Only their
digests are stored; expiry, revocation and account disabling are checked on each
request. No global environment token automatically acquires an owner or grant.
This replaces the initial OAuth-only restriction at the user's request.
Service-wide settings contain only transport, store and
identity bootstrap.

Managed cache URLs use `/view/VIEW/cache/TOKEN` with per-owner/view signatures
and require the same owner's OAuth or browser authorization. Signed URLs are not
standalone access grants. Reserved `admin`, `search`, and `_search` view names
cannot be supplied in user config.

## Compatibility and limitations

Preserve root OAuth discovery and client registration; mounted resource metadata
must be tested against the earlier failures recorded in security plan `1ff53bcd`.
All managed views share the public origin as their OAuth resource and new token
audience. The previous `/mcp` audience is an explicit verification compatibility
alias, with all signature/issuer/expiry/type checks retained. The previous
protected-resource metadata path remains an alias to the shared metadata.
View authorization remains a separate check on every request; token issuance
never mutates the shared resource based on an incoming view path.
Do not promise that host discovery caches update automatically. Manual tool refresh
is an explicit fallback. Stateless HTTP can recover transport without losing
authorization; a lost transport session is distinct from a required OAuth login.

User ownership prevents an accidentally admitted valid identity from inheriting
another person's configuration. It is not a sandbox for trusted operator code and
cannot compensate for a verifier accepting forged claims for the real owner.

## Verification

Test colliding user/view/server names, changed identity on reused sessions,
unprovisioned logins under a broad allowlist, indirect tool calls, secret references,
signed cache links, failed preparations, conflict races, old-call draining and
process restarts. Run the project's full 100% coverage gate without weakening it.
