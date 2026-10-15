---
id: 035-m4-pass-core-release-quality-and-acceptance-gate
sequence: 35
slug: m4-pass-core-release-quality-and-acceptance-gate
name: 'M4: Pass core release quality and acceptance gate'
status: blocked
order: 34
depends_on:
    - 034-m4-rehearse-migration-and-release-rollback
    - 031-m4-exercise-live-update-concurrency-and-failure-recovery
    - 019-m2-prove-end-to-end-oauth-user-isolation
created_at: 2026-10-13T15:04:00.269413Z
updated_at: 2026-10-15T16:53:30.52283Z
---

Run make check and make test with existing 100% branch-aware coverage, review endpoint/auth compatibility and all brief acceptance criteria, fix failures, and record commands/results. Reconcile follow-ups with security plan without marking its unrelated tasks complete. Acceptance: user-owned config, mobile browser live apply and auth restart evidence complete; no core dependence on MCP Apps or optional upstream forwarding. Local implementation, protocol tests and sandbox/mobile-viewport browser tests pass. Deployment updated 2026-10-15: migrated real Auth0 state, preserved a pre-switch credential through migration and another process restart, and verified loopback/public endpoints. Actual Claude/ChatGPT account/device UI and refresh behavior remain pending; stored sessions had no refresh tokens. See the deployment section of the acceptance record. See docs/specs/remote-configuration-acceptance.md.
