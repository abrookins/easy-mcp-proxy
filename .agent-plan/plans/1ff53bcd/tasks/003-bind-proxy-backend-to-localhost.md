---
id: 003-bind-proxy-backend-to-localhost
sequence: 3
slug: bind-proxy-backend-to-localhost
name: Bind proxy backend to localhost
status: not_started
order: 2
depends_on:
    - 002-restrict-public-edge-routes-to-required-mcp-endpoints
created_at: 2026-07-07T19:33:04.735152Z
updated_at: 2026-07-07T19:33:04.735159Z
---

Add or wire a host option for HTTP serving if needed, then update launchd/runtime config so Uvicorn listens on 127.0.0.1 behind the edge proxy instead of 0.0.0.0.
