---
id: 037-m5-validate-private-mcp-apps-compatibility
sequence: 37
slug: m5-validate-private-mcp-apps-compatibility
name: 'M5: Validate private MCP Apps compatibility'
status: blocked
order: 36
depends_on:
    - 035-m4-pass-core-release-quality-and-acceptance-gate
    - 003-m0-establish-client-and-mobile-compatibility-matrix
assignee: codex
created_at: 2026-10-13T15:04:00.354485Z
updated_at: 2026-10-15T16:53:30.55973Z
---

Refresh primary docs and build a minimal non-mutating UI resource against actual Claude and ChatGPT accounts. Verify standard _meta.ui.resourceUri, UI MIME, host bridge, resource auth, private installation, sandbox/CSP and mobile availability. Acceptance: dated capability matrix and reusable adapter contract; no promise of untested native mobile parity or vendor-specific API dependency. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Deployment updated 2026-10-15: migrated real Auth0 state, preserved a pre-switch credential through migration and another process restart, and verified loopback/public endpoints. Actual Claude/ChatGPT account/device UI and refresh behavior remain pending; stored sessions had no refresh tokens. See the deployment section of the acceptance record. See docs/specs/remote-configuration-acceptance.md.
