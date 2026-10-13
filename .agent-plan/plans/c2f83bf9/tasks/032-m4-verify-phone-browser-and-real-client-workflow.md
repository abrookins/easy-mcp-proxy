---
id: 032-m4-verify-phone-browser-and-real-client-workflow
sequence: 32
slug: m4-verify-phone-browser-and-real-client-workflow
name: 'M4: Verify phone browser and real client workflow'
status: blocked
order: 31
depends_on:
    - 029-m3-build-responsive-user-specific-administration-ui
    - 028-m3-add-remote-administration-cli
    - 031-m4-exercise-live-update-concurrency-and-failure-recovery
    - 008-m1-verify-authentication-across-actual-process-restarts
    - 019-m2-prove-end-to-end-oauth-user-isolation
    - 003-m0-establish-client-and-mobile-compatibility-matrix
created_at: 2026-10-13T15:04:00.134721Z
updated_at: 2026-10-13T16:41:07.705117Z
---

Execute first-release scenario: edit/preview/apply a view from a phone browser during a long tool call, keep unchanged upstreams and other user sessions alive, verify tool behavior in Claude and ChatGPT, and restart to verify auth refresh. Record device/client versions and required discovery refresh. Acceptance: supported surfaces pass with evidence; unavailable native mobile Apps explicitly documented and do not block browser milestone. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Remaining external gate: actual Claude/ChatGPT account/device installation and refresh tests, plus production Auth0/deployment restart verification; these are unavailable in this session and have not been reported as passed. See docs/specs/remote-configuration-acceptance.md.
