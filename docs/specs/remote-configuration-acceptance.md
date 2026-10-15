# Acceptance record: user-owned live configuration

Plan: `c2f83bf9`. Branch: `feat/user-owned-live-configuration`.
Initial evidence date: 2026-10-13; deployment evidence added 2026-10-15. This
record distinguishes automated local verification from deployment/device
acceptance. The running service now uses this branch; see the deployment section.

## Architecture and implementation evidence

| Requirement | Evidence |
| --- | --- |
| Explicit issuer/subject ownership; no global fallback | `identity.py`, `user_store.py`, managed HTTP/stdio entry points; unprovisioned valid-token tests |
| Different users at identical URLs and names | Wire MCP initialize/list/call tests for default/named views; per-client grant revocation |
| Request-scoped indirect execution | Concurrent custom-tool/hook tests, aliases/hidden defaults/compositions, existing search helper suite |
| Separate operator capabilities | Service-layer tests reject commands, hooks, custom tools, metadata-server URLs, and host env interpolation for nonoperators |
| Encrypted state and stable keys | File permissions, corrupt/missing-key tests; ciphertext marker tests; separate key purposes |
| OAuth upgrade compatibility | Legacy FastMCP v3 fixture import preserves signed token verification and encrypted DCR records, rebasing collection paths |
| Actual proxy process restart | `helpers_user_restart.py` seeds state in one process and verifies access, refresh exchange, browser session, root/named resource discovery in another; identity provider is mocked |
| Immutable activation and failure recovery | Revision conflicts, cancelled preparation, temporary probe cleanup, failed commit, interrupted recovery, per-user generation leases |
| Connection retention and draining | Unchanged clients reused; changed clients drain; 10-second policy tested with shorter deterministic timeout; real subprocess PID retained |
| Cache isolation | Per-owner/view HMAC keys; HTTP and MCP cache resource tests reject other owners/views |
| API/CLI/browser | Scoped operations, 1 MiB HTTP bound, CSRF, callback state/PKCE/client binding, single-use state, logout, persistence, secure credential sources |
| MCP admin tools | Dedicated granted admin endpoint, typed operations, annotations, 64 KiB bounds, raw-secret rejection, scoped resource auth |
| Notifications | Actual MCP apply response stream contains `notifications/tools/list_changed`; idle stateless clients require manual tool refresh |
| Migration and release reversal | `test_user_rehearsal.py`: explicit import, backup, real upstream, live edit/PID retention, separate-process reload, restore, unchanged-YAML reverse path |

The baseline suite had one unrelated failure: a sibling Upskill source build
reported `dev` while its integration fixture expected `0.1.0`. The fixture now
injects that test version at Go build time; the version assertion remains intact.

## Browser and portable UI evidence

Playwright runs Chromium with a **390 × 844** viewport against a loopback fixture
using the production gateway and real MCP HTTP requests. Passing scenarios:

- Browser preview/apply, per-user empty state, second-tab stale edit rejection,
  rollback preview/apply, no horizontal overflow, and logout.
- Sandboxed iframe (`allow-scripts`, without same-origin access) running the
  bundled standard MCP Apps SDK, preview/apply through the host bridge, browser
  fallback link, and rejection of inline credential input.
- Add/probe an upstream, start a long MCP tool call, edit/apply a view from the
  phone-sized browser, and verify the original call finishes successfully.

Screenshots are generated locally as `test-results/phone-admin.png` and
`test-results/embedded-admin.png`; they contain only synthetic fixture identities.
The test host is a protocol fixture, **not Claude or ChatGPT**. The production
package has no `/test/*` routes.

Reproduce:

```sh
uv sync
make check
make test
npm ci
npx playwright install chromium
npm run build:ui
npm run check:ui
npm run test:ui
```

`embedded.html` is the committed bundle; rebuilding must produce no diff.
Playwright and the build tooling are development dependencies only. Serving the
browser UI requires no Node process or separate frontend deployment.

## Host compatibility and remaining external checks

| Surface | Evidence / status |
| --- | --- |
| Phone-sized browser | Passed in automated Chromium; physical Safari/Chrome phone run pending |
| Portable MCP Apps SDK and sandbox bridge | Passed locally with SDK 2.0.3 and standard wire messages |
| Claude web/desktop private connector | Official docs describe support; actual account installation, refresh and embedded flow pending |
| Claude native iOS/Android | Official docs describe interactive connectors; this private connector on actual devices pending |
| ChatGPT custom MCP app on web | Official developer docs describe standard MCP UI; actual account feature/plan access and refresh pending |
| ChatGPT native iOS/Android custom app | Not established for this account; do not claim native parity |
| Existing production Auth0/deployment restart | Migrated and verified 2026-10-15 with real Auth0-backed credentials; interactive client and refresh-token checks remain pending |

Primary references checked 2026-10-13:
[standard overview](https://modelcontextprotocol.io/extensions/apps/overview),
[standard SDK](https://apps.extensions.modelcontextprotocol.io/api/),
[OpenAI MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui),
[Claude interactive connectors](https://support.claude.com/en/articles/13454812-use-interactive-connectors-in-claude).
The baseline report records the separate custom-app availability constraint.
Documentation is not evidence that this private service has been installed and
tested on those accounts.

For each real client, record application/OS version, account plan, connector URL,
OAuth client ID (never tokens), initial tools, observed tool-refresh behavior,
embedded UI availability, and post-restart access/refresh. Use synthetic or
non-sensitive tool calls. Verify root discovery and the existing named-view
resource flow before migrating production. The related security plan `1ff53bcd`
remains independent; no tasks in it were changed.

These external checks remain release gates. Local implementation and automated
checks must not be reported as a production rollout or native-device acceptance.

## Optional upstream Apps forwarding decision

**Deferred**, independently of proxy-owned administration. The current ToolInfo
pipeline intentionally normalizes tool schemas/results, search helpers change
call names, and upstream UI resources would need a separate owner/server URI
namespace, resource authorization, tool alias translation, and output policy.
Simply preserving `_meta.ui` would advertise resources the proxy cannot securely
serve. No third-party UI forwarding contract is claimed. The optional forwarding
implementation/QA tasks are cancelled according to the plan's default-defer rule.

## Final local check results

- `make check`: passed (Ruff lint and formatting).
- `make test`: **1308 passed**, **100% line and branch coverage**; 12.58 seconds
  in the recorded run. No coverage exclusions or threshold reductions were added.
- `npm run build:ui` and `npm run check:ui`: passed.
- `npm run test:ui`: **3 passed** in 9.5 seconds, including the long-call scenario.
- Isolated migration/restart/restore rehearsal: passed; its initial focused run
  completed in 1.87 seconds. Included again in the full suite.

Real-account/native-device and production Auth0 checks above remain pending;
they are not included in these passing counts.

## Documentation audit: 2026-10-15

Plan task 044 aligned the README, tutorial, reference, examples, discovery guide,
operator guide, and agent guide with managed serving. Historical ADRs and baseline
specs now point readers to the current implementation and acceptance evidence.
The audit corrected file-based startup instructions, grant semantics, reserved
view names, cache authorization, removed HTTP routes, and rollback procedures.

Verification for this documentation update:

- README and tutorial YAML/bootstrap sequences passed against disposable state:
  validation, provisioning, grants, dry-run import, apply, and idempotent reimport.
  These checks did not start upstreams or exercise an actual desktop client.
- 105 relative Markdown links and their heading targets resolved across 21 files.
- CLI options and managed routes were checked against the local implementation.
- `make check` passed; `make test` passed with **1308 tests** and **100% line and
  branch coverage** in 12.72 seconds. No application code or tests were changed.
- The earlier browser/UI results above were not rerun for this prose-only update.

The five real-environment checks/release gates remain pending. This audit did not
migrate production, verify physical phones, or establish native MCP Apps support.


## Deployment verification: 2026-10-15

The user authorized stopping the existing service and starting this branch.
The launchd service now runs from the feature checkout with managed state; its
port and public origin are unchanged. The old deployment checkout remains intact
for rollback. The private migration directory contains the original launchd plist,
bootstrap environment, YAML/overrides, encrypted OAuth store, and verification
reports. Credential files and identity details are not committed here.

Preflight identified an activation bug: tools sharing a name across different
upstreams were rejected even in `search_per_server` mode. Commit `904a61b` scopes
that collision check by server while still rejecting duplicates within a server.
Regression tests call both same-named tools and reject duplicate aliases in all
three exposure modes. `make check` passed; `make test` passed with **1311 tests**
and **100% line and branch coverage**. The real configuration then initialized
all eight upstreams in an isolated rehearsal.

Deployment evidence:

- Verified the existing owner against Auth0 and provisioned that issuer/subject.
- Imported compatible FastMCP 3.4.3 OAuth state with the existing signing key;
  checked all 135 backed-up files byte-for-byte before import.
- Preserved four currently authenticated Claude application registrations with
  runtime view grants. Browser/local administration grants are separate.
- Imported effective YAML/overrides into encrypted state. The original files
  remain unchanged and are no longer the serving configuration.
- MCP discovery retained every previous exposed tool. `range_cached_output` was
  added: default view 4 → 5 tools, coding-agent 28 → 29, remote 19 → 20.
- Issued a short-lived operator probe credential **before** switching, referencing
  an existing verified Auth0 session. The same credential passed authenticated
  discovery after migration and again after a second process restart. This is
  server-side verification, not an interactive Claude/ChatGPT acceptance run.
- Loopback and public HTTPS health, root resource metadata, and verified identity
  requests passed. Unauthenticated MCP and the old static bearer returned 401.
- Existing stored Auth0 sessions had no refresh tokens. Refresh exchange and
  expiry/re-login behavior therefore remain unverified on the real installation.

The first stop attempt did not release the listener within its deadline, so the
previous launchd configuration was restored before retrying. The successful
attempt verified listener shutdown before copying OAuth state. The final service
passed another restart and authenticated discovery check.

### Agent connection changes

Keep existing MCP URLs. For the current Codex connection, keep
`http://127.0.0.1:8000/view/coding-agent/mcp`, remove its static `Authorization`
header, and run `codex mcp login proxy`. A newly registered OAuth application's
client ID needs an explicit local grant for `coding-agent` before tool access;
then restart/reconnect the agent. Login does not provision or grant access.
The agent configuration was not edited as part of this service switch.

Existing granted Claude registrations can keep their endpoints and OAuth state;
a new registration or an expired upstream session may still require login and
a new explicit grant. Browser administration is at `/config`. For embedded
administration, use a separate `/view/admin/mcp` connector with both admin and
`admin` view grants. Physical-device and actual-host UI checks remain pending.

### Live OAuth compatibility repair: 2026-10-15

Claude Desktop through `mcp-remote` exposed a discovery mismatch: the named
`/view/remote/mcp` endpoint advertised `/mcp` as its resource. The actual MCP
TypeScript SDK reproduced this rejection against the running service. Browser
logs separately showed `invalid_scope` before reaching Auth0: the composite auth
wrapper supplied an empty scope instead of the OAuth backend's required scopes.

Commit `dac6ff4` fixes both issues and is deployed on the existing launchd service:

- Shared-origin resource metadata and newly issued token audiences cover every
  managed view. Explicit legacy `/mcp` token verification retains signature,
  issuer, expiry, token-type, owner and grant checks; no per-request issuer mutation.
- Existing protected-resource discovery URLs remain aliases. The actual MCP
  TypeScript SDK accepts public discovery at default, remote, coding-agent and
  search endpoints after restart.
- Browser login uses the backend's required scopes and omits an empty scope.
  Public login initiation reaches the consent page without the former error.
  Auth0 configuration was not changed.
- Short-lived operator probes backed by an existing verified Auth0 session pass
  identity checks on loopback and public HTTPS with both token audiences, and
  both return all 20 remote tools. Static bearer authentication remains rejected.
- Real OAuth handler tests exercise browser authorization, PKCE exchange and
  session creation with a simulated IdP result. Process tests verify legacy
  access and refresh token migration. `make check` and all **1314 tests** pass
  with **100% line and branch coverage**.

Private deployment evidence is recorded with the original migration backup.
Interactive Auth0 completion and actual Claude Desktop reconnection remain
user-side checks; this repair does not complete the pending real-host/mobile
acceptance gates. Claude's static `Authorization`/`AUTH_TOKEN` configuration must
be removed so `mcp-remote` can perform OAuth; newly registered clients still need
explicit grants. See the [Claude configuration](../user-owned-configuration.md#claude-desktop-through-mcp-remote).
