---
id: 005-add-edge-rate-limiting-and-request-size-limits
sequence: 5
slug: add-edge-rate-limiting-and-request-size-limits
name: Add edge rate limiting and request size limits
status: not_started
order: 4
depends_on:
    - 002-restrict-public-edge-routes-to-required-mcp-endpoints
created_at: 2026-07-07T19:33:16.015489Z
updated_at: 2026-07-07T19:33:16.015498Z
---

Configure edge-level method restrictions, per-IP request limits, burst behavior, and client body size caps for the public MCP routes. Keep scanner noise from consuming Python app resources.
