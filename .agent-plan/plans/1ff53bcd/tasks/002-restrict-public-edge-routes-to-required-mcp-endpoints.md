---
id: 002-restrict-public-edge-routes-to-required-mcp-endpoints
sequence: 2
slug: restrict-public-edge-routes-to-required-mcp-endpoints
name: Restrict public edge routes to required MCP endpoints
status: in_progress
order: 1
depends_on:
    - 001-create-least-privilege-remote-mcp-view
created_at: 2026-07-07T19:32:59.439393Z
updated_at: 2026-08-14T05:24:28.437495Z
---

Configure the public edge proxy to pass only the required MCP endpoint, likely /view/remote/mcp, plus any required OAuth discovery metadata. Drop or reject scanner paths and unrelated routes before they reach the Python app.
