# Tool Discovery, Inspection, and Safe Calls

Easy MCP Proxy builds one canonical metadata record after schema reference
resolution, view filtering, tool and parameter renames, hidden defaults, and
description overrides. Search results, description calls, validation, the CLI,
generated instructions, and the web registry all read that record.

## Exposure modes

`direct` registers every exposed tool by its final name. `search` registers
three meta-tools for the view:

- `<view>_search_tools` finds tools and can include complete schemas with
  `include_schema: true`.
- `<view>_describe_tool` returns one exact canonical record, including
  `inputSchema`, accepted parameter names, and dry-run support.
- `<view>_call_tool` validates exposed arguments before invoking the upstream
  tool.

`search_per_server` registers the same search, describe, and call trio for each
upstream server. For a server named `skills`, the names are
`skills_search_tools`, `skills_describe_tool`, and `skills_call_tool`.

A safe agent sequence is search, describe, call with preview arguments, review
the result, then call again to apply. A search result is compact by default;
use its accepted names or request the schema instead of guessing arguments.

## CLI inspection

The raw upstream and final exposed interfaces are intentionally separate:

```bash
# Environment-dependent: requires the configured upstream server to be running.
mcp-proxy schema skills.promote_skill_draft --config config.yaml

# Environment-dependent: shows renames, hidden parameters, and defaults.
mcp-proxy schema --view default promote_skill_draft --config config.yaml

# Environment-dependent: stable canonical JSON for every tool in a view.
mcp-proxy schema --view default --json --config config.yaml

# Environment-dependent: compact and verbose view inventories.
mcp-proxy tools --view default --json --config config.yaml
# Environment-dependent: requires the configured upstream server to be running.
mcp-proxy tools --view default --verbose --json --config config.yaml
```

Human schema output lists accepted parameter names and whether `dry_run` is a
boolean input. JSON uses the same canonical field names as the describe
meta-tool. Connection failures, unknown views, and unknown tools use distinct
errors; close names include a conservative suggestion.

## Web Tools tab and API

For HTTP serving, open `/config` and select **Tools**. The read-only tab has a
view selector, name/description filter, accepted-parameter badges, a dry-run
badge, expandable JSON Schema, registry status, and snapshot timestamp. It does
not expose tool execution.

`GET /config/api/tools?view=default` returns the same canonical records. It
accepts the browser session cookie or the same bearer authentication as other
operator routes. The response also includes `tool_count`, a deterministic
`schema_hash`, status, warnings, and upstream refresh errors for rollout checks.

## Compatibility and rollout

| Proxy | Upstream | Expected behavior |
| --- | --- | --- |
| Previous | Updated Upskill | Existing valid calls work; direct Upskill clients get richer errors and `describe_tool`. |
| Updated | Previous Upskill | Valid calls work; the proxy teaches and validates any schema the previous server publishes. |
| Updated | Updated Upskill | Full search, describe, pre-call validation, canonical source identity, and preview contract. |

Deploy Upskill first or independently, record its tool count and schema hash,
then deploy the proxy after the compatibility suite passes. Refresh upstream
clients and compare the hosted `/config/api/tools` count and hash with staging.
The proxy can be rolled back without rolling back Upskill. Upskill can be
rolled back separately because proxy metadata is additive and valid direct
calls retain their wire shape.

### Roll back Upskill independently

Before deployment, record the Upskill commit, binary SHA-256, configured
command, `UPSKILL_HOME`, and `UPSKILL_CONFIG`. Build the candidate into a new
versioned path and run the stdio lifecycle suite against the real configuration
without replacing the active binary. After activation, restart or refresh the
proxy's Upskill client and record the hosted tool count and schema hash.

To roll back only Upskill:

1. Restore the previous configured command or versioned binary; do not change
   the proxy package.
2. Restart or refresh the proxy's Upskill client so it discards cached tool
   metadata.
3. Confirm the server identity, previous tool count/hash, and one read-only
   description call.
4. Re-run a preview against a disposable source and verify no state change.

Upskill's registry and preview changes require no configuration or state
migration. Do not delete drafts, sources, overlays, or installed skills during
rollback.

### Roll back Easy MCP Proxy independently

Before deployment, record the proxy commit, `uv.lock` hash, config path,
launchd label, and hosted registry snapshot. The known central launchd service
is `com.andrewbrookins.easy-mcp-proxy`; verify that live service metadata before
using it because deployment hosts may differ.

To roll back only the proxy:

1. Stop the service and select the previous clean proxy commit. Leave the
   Upskill binary and configuration unchanged.
2. Run `uv sync --frozen`, then start the service with
   `launchctl kickstart -k gui/$(id -u)/com.andrewbrookins.easy-mcp-proxy` on
   the host that owns the launchd job.
3. Verify `/health`, then compare `/config/api/tools` with the saved previous
   snapshot.
4. Run search, describe, and one read-only call through the same production
   view used by clients.

Do not edit source or state directories as part of a proxy rollback. If either
service fails its smoke test, keep the other service at its independently
verified version.

## Troubleshooting

Unknown argument key:

- Read `accepted_parameter_names`, `unknown_parameter_names`, and
  `did_you_mean` from `tool_validation_failed`.
- Call the describe meta-tool and resend only exposed names. A hidden upstream
  name is never valid at the proxy boundary.

Stale instructions:

- Treat the live describe response and `/config/api/tools` snapshot as
  authoritative.
- Refresh the upstream connection. If the timestamp advances but the tool set
  does not, compare `schema_hash` and inspect `warnings` and `upstream_errors`.

Ambiguous Upskill source:

- Use the stable `src_...` identifier returned in `canonical_resources` or
  `upskill source list --json`.
- Do not retry with source paths copied from an error; ambiguity errors list
  only safe display names and IDs.

Preview mismatch:

- Confirm the described `dry_run` default instead of adding the flag to tools
  that do not advertise it.
- Require `dry_run: true`, `applied: false`, deterministic actions, and no state
  change before approval.
- On apply, compare operation and target pairs and perform a read-back. A
  partial failure reports action statuses and never claims full application.
