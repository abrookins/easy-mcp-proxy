---
id: 039-m5-validate-embedded-ui-isolation-and-host-behavior
sequence: 39
slug: m5-validate-embedded-ui-isolation-and-host-behavior
name: 'M5: Validate embedded UI isolation and host behavior'
status: blocked
order: 38
depends_on:
    - 038-m5-add-portable-embedded-administration-screens
assignee: codex
created_at: 2026-10-13T15:04:00.442834Z
updated_at: 2026-10-13T16:41:07.952629Z
---

Test sandbox/CSP, resource auth, app tool visibility, concurrent/stale component instances, credential redaction, unauthorized mutations and user/session isolation. Exercise actual supported Claude/ChatGPT surfaces; recheck iOS/Android custom app availability. Acceptance: portable flows pass with versioned evidence; missing capabilities lead to clear browser fallback; core service remains usable without UI support. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Remaining external gate: actual Claude/ChatGPT account/device installation and refresh tests, plus production Auth0/deployment restart verification; these are unavailable in this session and have not been reported as passed. See docs/specs/remote-configuration-acceptance.md.
