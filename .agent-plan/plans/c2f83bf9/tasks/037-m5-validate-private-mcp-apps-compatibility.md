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
updated_at: 2026-10-13T16:41:07.882398Z
---

Refresh primary docs and build a minimal non-mutating UI resource against actual Claude and ChatGPT accounts. Verify standard _meta.ui.resourceUri, UI MIME, host bridge, resource auth, private installation, sandbox/CSP and mobile availability. Acceptance: dated capability matrix and reusable adapter contract; no promise of untested native mobile parity or vendor-specific API dependency. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Remaining external gate: actual Claude/ChatGPT account/device installation and refresh tests, plus production Auth0/deployment restart verification; these are unavailable in this session and have not been reported as passed. See docs/specs/remote-configuration-acceptance.md.
