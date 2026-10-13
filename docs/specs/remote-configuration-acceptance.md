# Acceptance record: user-owned live configuration

Plan: `c2f83bf9`. Branch: `feat/user-owned-live-configuration`.
Evidence date: 2026-10-13. This record distinguishes automated local verification
from deployment/device acceptance. The production checkout and service have not
been modified.

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
| Existing production Auth0/deployment restart | Not executed; local tests use real SDK persistence with a mocked identity provider |

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
