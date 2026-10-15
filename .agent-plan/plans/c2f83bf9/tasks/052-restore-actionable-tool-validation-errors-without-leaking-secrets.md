---
id: 052-restore-actionable-tool-validation-errors-without-leaking-secrets
sequence: 52
slug: restore-actionable-tool-validation-errors-without-leaking-secrets
name: Restore actionable tool validation errors without leaking secrets
status: not_started
order: 51
depends_on:
    - 051-investigate-misleading-errors-from-skills-tool-calls
created_at: 2026-10-15T21:14:01.212792Z
updated_at: 2026-10-15T21:14:01.212801Z
---

Investigation 051 reproduced gateway error masking. ScopedTool.run catches every inner exception, including safe local ToolArgumentValidationError/unknown-tool errors and upstream tool rejections, and mislabels them as connection health failures. Preserve bounded explicitly safe structured validation errors; distinguish tool rejection from actual transport/auth errors; keep arbitrary exception/secret masking. Skills overlay operation schema should enumerate append/root_append/files/replace/template/patch so add is rejected clearly before execution (coordinate the upstream schema change). Cover live managed wire paths, invalid source/operation/unknown argument, no retries for deterministic failures, redaction, and successful dry runs.
