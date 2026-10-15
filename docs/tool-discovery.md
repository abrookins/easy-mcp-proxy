# Tool Discovery, Inspection, and Safe Calls

Easy MCP Proxy builds one canonical metadata record after schema reference
resolution, view filtering, tool and parameter renames, hidden defaults, and
description overrides. Search results, description calls, validation, the CLI,
and generated instructions read that record. In the managed service, discovery
uses the current authenticated owner's active generation and selected view.

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

These CLI commands inspect a local YAML file and may start upstream processes.
They do not read the running service's managed store. The raw upstream and final
exposed interfaces are separate:

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

## Live discovery and browser administration

Connect an OAuth MCP client to a granted `/mcp`, `/view/NAME/mcp`, or `/search/mcp`
endpoint. Use MCP `tools/list` for the live exposed schemas. In search modes,
use the advertised search/describe helpers to inspect individual upstream tools.
Each request resolves the current owner and checks that client's view grant.

`/config` provides configuration editing, preview/probe/apply, status, history,
and rollback. It does **not** contain the legacy Tools registry tab, and the
managed gateway does not expose `/config/api/tools`. Use live MCP discovery for
schema evidence. `manage status` reports desired/runtime revisions and upstream
state; a probe reports temporary connectivity and tool count, not a full registry
snapshot or schema hash.

An apply through the admin MCP endpoint sends `notifications/tools/list_changed`
on the active request stream. A browser edit cannot broadcast to idle clients.
Refresh client discovery explicitly and verify behavior against the
[client acceptance checklist](specs/remote-configuration-acceptance.md#host-compatibility-and-remaining-external-checks).

## Compatibility and rollout

Canonical descriptions and argument validation work with the schemas an upstream
publishes. Updated upstreams may provide richer schemas and errors; the proxy
does not invent parameters missing from those schemas. Verify both the raw
upstream interface and the final exposed interface when upgrading either side.

Before deployment, record the proxy/upstream versions, active managed revision,
client/view grants, and a live MCP tool/schema snapshot. Compare tool names,
counts, and schemas after activation, using the same identity and view. Keep
configuration exports and credentials out of the evidence record.

### Roll back Upskill independently

The same sequence applies to other local upstreams. Record the Upskill version,
binary checksum, `UPSKILL_HOME`, and `UPSKILL_CONFIG` before changing its command.

1. Keep the previous executable at a separate versioned path. Test the candidate
   in an isolated environment before changing the managed configuration.
2. As an operator administrator, preview a change to the upstream command/path,
   probe it, then apply. A changed command prepares a replacement worker.
3. Refresh client discovery and verify a read-only call through the same view.
4. To reverse the change, preview/apply the previous command/path, or use a
   rollback preview of a retained revision. Verify again.

Reapplying an unchanged command does not force a worker replacement. Use versioned
paths when changing local executables. Upskill's registry/preview additions
require no configuration or state migration in Upskill itself; this does not
waive the proxy's managed-state migration. Do not delete drafts, sources, overlays,
or installed skills during either rollback.

### Roll back Easy MCP Proxy independently

For an in-app configuration reversal, preview/apply a retained revision. That
operation preserves the installed proxy version and uses current permissions.

For a release reversal, follow the [backup and restore procedure](user-owned-configuration.md#backup-restore-rotation-and-rollback).
Record the executable, lockfile, service-manager configuration, state path, keys,
OAuth store, and public origin before upgrading. Stop the runtime before copying
or restoring state. A return to the old global-config service requires its
pre-upgrade YAML/overrides and compatible OAuth state; changing only the commit
is insufficient.

For a macOS launchd user service, verify its job label and launch configuration
before restarting the restored version. With `PROXY_LAUNCHD_LABEL` set to that
verified label, the restart command is:

```bash
launchctl kickstart -k "gui/$(id -u)/${PROXY_LAUNCHD_LABEL}"
```

Run it only after restoring the intended executable and compatible state. Other
service managers require their own restart command.

Verify `/health`, live MCP discovery, a read-only call, and OAuth refresh after
restore. Production migration and real-client restart verification remain
[release gates](specs/remote-configuration-acceptance.md).

## Troubleshooting

Unknown argument key:

- Read `accepted_parameter_names`, `unknown_parameter_names`, and
  `did_you_mean` from `tool_validation_failed`.
- Call the describe meta-tool and resend only exposed names. A hidden upstream
  name is never valid at the proxy boundary.

Stale instructions:

- Treat live MCP `tools/list` and describe responses for the same user/view as
  authoritative; a local YAML inspection may describe a different revision.
- Compare desired/runtime revisions with `manage status`. If the active runtime
  is current but the client shows old tools, refresh its connector/tool list.
- If an upstream binary changed in place, publish a configuration referencing a
  new versioned path so the runtime replaces that worker.

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
