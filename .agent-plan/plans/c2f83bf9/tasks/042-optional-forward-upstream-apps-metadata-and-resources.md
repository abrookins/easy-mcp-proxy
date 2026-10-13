---
id: 042-optional-forward-upstream-apps-metadata-and-resources
sequence: 42
slug: optional-forward-upstream-apps-metadata-and-resources
name: 'Optional: Forward upstream Apps metadata and resources'
status: cancelled
order: 41
depends_on:
    - 041-optional-decide-upstream-mcp-apps-forwarding-scope
created_at: 2026-10-13T15:04:00.582914Z
updated_at: 2026-10-13T16:41:08.054463Z
---

Execute only after proceed decision; otherwise cancel. Preserve _meta.ui and required result metadata, namespace and authorize resources by user/server, translate resource/tool names consistently, enforce UI call grants and sandbox policy, and define direct/search exposure behavior. Preserve structured results without bypassing output limits. Acceptance: two upstreams/users with colliding URIs/tool names work correctly; unsupported combinations give explicit fallback. Deferred by task 041 per the explicit default-defer rule. Proxy-owned administration is implemented; upstream resource forwarding needs a separate authorization/namespacing design.
