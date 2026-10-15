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
updated_at: 2026-10-15T16:53:30.594019Z
---

Test sandbox/CSP, resource auth, app tool visibility, concurrent/stale component instances, credential redaction, unauthorized mutations and user/session isolation. Exercise actual supported Claude/ChatGPT surfaces; recheck iOS/Android custom app availability. Acceptance: portable flows pass with versioned evidence; missing capabilities lead to clear browser fallback; core service remains usable without UI support. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Deployment updated 2026-10-15: migrated real Auth0 state, preserved a pre-switch credential through migration and another process restart, and verified loopback/public endpoints. Actual Claude/ChatGPT account/device UI and refresh behavior remain pending; stored sessions had no refresh tokens. See the deployment section of the acceptance record. See docs/specs/remote-configuration-acceptance.md.
