---
id: 040-m5-complete-embedded-administration-release-gate
sequence: 40
slug: m5-complete-embedded-administration-release-gate
name: 'M5: Complete embedded administration release gate'
status: blocked
order: 39
depends_on:
    - 039-m5-validate-embedded-ui-isolation-and-host-behavior
assignee: codex
created_at: 2026-10-13T15:04:00.488723Z
updated_at: 2026-10-13T16:41:07.98601Z
---

Update user/operator docs with installation and host capability matrix; run make check, make test and UI build/checks appropriate to added code. Record acceptance evidence and limitations. Acceptance: admin MCP tools and portable UI are documented, permission-equivalent to browser, and do not regress core milestones; optional forwarding remains independent. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Remaining external gate: actual Claude/ChatGPT account/device installation and refresh tests, plus production Auth0/deployment restart verification; these are unavailable in this session and have not been reported as passed. See docs/specs/remote-configuration-acceptance.md.
