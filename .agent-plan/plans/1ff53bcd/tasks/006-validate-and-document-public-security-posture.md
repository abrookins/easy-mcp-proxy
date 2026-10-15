---
id: 006-validate-and-document-public-security-posture
sequence: 6
slug: validate-and-document-public-security-posture
name: Validate and document public security posture
status: not_started
order: 5
depends_on:
    - 003-bind-proxy-backend-to-localhost
    - 004-harden-authentication-and-token-management
    - 005-add-edge-rate-limiting-and-request-size-limits
created_at: 2026-07-07T19:33:24.322783Z
updated_at: 2026-07-07T19:33:24.322798Z
---

Verify remote clients still work, unauthorized requests fail, scanner-style paths are dropped at the edge, the backend is not directly reachable externally, and the operational runbook/docs explain the exposed routes and auth model.
