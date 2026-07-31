# Safe Default Output Handling

## Status

Draft

## Problem

A live proxied filesystem call returned an entire roughly 363k-token file even
though Easy MCP Proxy already exposes cached-output navigation tools. The
current output caching implementation is opt-in and is not applied uniformly
across all visible proxy call paths. This makes large downstream responses a
context-window hazard and lets one upstream MCP server overwhelm a client even
when other upstreams have safer behavior.

The proxy should treat output protection as a proxy responsibility. After an
upstream server returns a result, every proxied call path should measure the
result, cache oversized content, and return only a bounded preview with
navigation metadata.

## Current Findings

- `OutputCacheConfig.enabled` defaults to `False`, and `ProxyConfig.output_cache`
  is optional. With no explicit cache settings, no output protection is active.
- `ToolView.call_tool()` extracts and caches results only when a cache context
  exists and `get_cache_config()` returns a config.
- Direct root registration without a default view calls upstream tools through
  `_execute_direct_call()` and currently bypasses `ToolView.call_tool()`.
- The virtual `/search/mcp` view is initialized without a cache context, so its
  `{server}_call_tool` wrappers can bypass output caching even when global
  caching is enabled.
- Custom and composite tool branches in `ToolView.call_tool()` return early
  before output caching is considered.
- Existing previews are character-limited but not line-limited. A single
  minified JSON, JSONL, AOF, or log line can still dominate the preview.
- `retrieve_cached_output()` and the HTTP cache endpoint can return the full
  cached content by default. This works for compatibility, but it conflicts with
  bounded retrieval as the safe default.
- Cache metadata currently records `size_bytes` and `token`, but not both
  original and returned sizes, truncation reasons, line counts, or line
  truncation state.
- When `cache_secret` is omitted, callers can receive different generated
  secrets from different helper invocations. Cache signing should use one
  proxy-instance secret.

## Goals

1. Protect every externally visible proxied tool call after the downstream
   server responds.
2. Return at most 2k-4k estimated tokens inline by default.
3. Cache any result that exceeds the inline budget or contains overlong lines.
4. Return a preview plus cache identifier and explicit navigation instructions.
5. Require bounded line, character-range, or JSON-query retrieval for more
   model-visible content.
6. Cap individual returned line length in both initial previews and retrieval
   tools.
7. Record original size, returned size, truncation status, truncation reasons,
   and cache identifier for every protected result.
8. Preserve existing cache storage and signed URL machinery where it fits.

## Non-Goals

- Do not interrupt or stream-limit the upstream call before the downstream MCP
  server responds. This change protects the proxy response, not upstream
  execution memory.
- Do not require every upstream MCP server to implement output caching.
- Do not add a tokenizer dependency for this change. Use a conservative token
  estimate unless a tokenizer is already available in the process.
- Do not remove signed HTTP retrieval. Keep it for explicit user-authored code
  and external processing, but do not make full content the default tool-plane
  response.

## Recommended Design

Introduce a central output protection layer that runs after downstream tool
execution and before returning to the MCP client.

Recommended defaults:

```yaml
output_cache:
  enabled: true
  ttl_seconds: 3600
  max_inline_tokens: 3000
  token_chars_ratio: 4
  max_inline_chars: 12000
  max_line_chars: 1200
  retrieval_default_line_count: 100
  retrieval_max_line_count: 500
  retrieval_max_chars: 12000
```

`max_inline_chars` may be omitted in config and derived as
`max_inline_tokens * token_chars_ratio`. Operators may lower these limits. They
should only be able to raise them within a documented hard ceiling unless they
explicitly disable strict output protection for trusted local debugging.

Keep the `output_cache` key for compatibility, but treat it as the proxy's
output-handling configuration. Existing fields continue to work:

- `preview_chars` becomes a compatibility alias for `max_inline_chars` when it
  is lower than the derived inline budget.
- `min_size` remains a cache threshold hint, but it must not override the hard
  inline budget. A result is cached when it exceeds `min_size`,
  `max_inline_chars`, `max_inline_tokens`, or `max_line_chars`.
- `enabled: false` remains accepted as an explicit opt-out, but the default
  effective config should be enabled when no cache config is provided.

## Central Helper

Add a module such as `mcp_proxy/output_handling.py` with one public entry point:

```python
def protect_tool_output(
    result: Any,
    *,
    view_name: str | None,
    server_name: str | None,
    tool_name: str,
    config: OutputCacheConfig,
    cache_secret: str,
    cache_base_url: str,
) -> Any:
    """Return result unchanged when safe, or a bounded cached ToolResult."""
```

The helper should:

1. Serialize the visible result into cacheable text.
2. Measure original bytes, chars, estimated tokens, line count, and longest line.
3. Decide whether the result must be cached.
4. Build a preview bounded by both total chars and per-line chars.
5. Write the full serialized text to cache when protected.
6. Return a `ToolResult` containing the preview, resource links, and structured
   metadata.
7. Log or otherwise record the same measurements for pass-through results.

Serialization should preserve original text where possible. Avoid pretty
printing very large JSON before caching, because parsing and expansion can make
the proxy spend more CPU and memory after the upstream response already arrived.

## Protection Decision

Cache and truncate the visible return when any condition is true:

- `estimated_tokens > max_inline_tokens`
- `len(serialized_text) > max_inline_chars`
- `longest_line_chars > max_line_chars`
- `min_size is not None and size_bytes >= min_size`

Return the original result unchanged only when all measured dimensions are under
budget. Even when unchanged, emit measurement data to logs or debug metrics.

## Preview Rules

The initial preview should be generated from the cached original content and
must satisfy all active limits:

- Total preview content must be at or below `max_inline_chars`.
- Estimated preview tokens must be at or below `max_inline_tokens`.
- Each returned line must be at or below `max_line_chars`.
- If a line is clipped, append a short marker that includes the original line
  length and next character offset.
- If the full result has more content, include next line and/or character
  offsets in structured metadata.

For single-line giant content, the preview should show only the first
`max_line_chars` characters and expose character-range navigation. Line windows
alone are not enough for this case.

## Response Shape

Extend `CachedOutputResponse` while keeping current fields for compatibility:

```json
{
  "cached": true,
  "cache_id": "abc123def456",
  "token": "abc123def456",
  "truncated": true,
  "truncation_reasons": ["estimated_tokens", "max_line_chars"],
  "preview": "bounded preview...",
  "retrieve_url": "https://proxy.example.com/cache/abc123def456?...",
  "expires_at": "2026-07-31T18:30:00Z",
  "original": {
    "bytes": 1452000,
    "chars": 1419000,
    "estimated_tokens": 354750,
    "lines": 1,
    "longest_line_chars": 1419000
  },
  "returned": {
    "bytes": 5100,
    "chars": 5000,
    "estimated_tokens": 1250,
    "lines": 1,
    "line_truncated": true
  },
  "limits": {
    "max_inline_tokens": 3000,
    "max_inline_chars": 12000,
    "max_line_chars": 1200
  },
  "navigation": {
    "preview_tool": "preview_cached_output",
    "range_tool": "range_cached_output",
    "query_tool": "query_cached_output",
    "next_line_offset": null,
    "next_char_offset": 1200
  }
}
```

The text content returned to the model should include the bounded preview and a
short instruction to use `preview_cached_output`, `range_cached_output`, or
`query_cached_output` for more content.

## Retrieval Tools

Update cache retrieval so model-visible retrieval is bounded by default.

### `preview_cached_output`

Keep the existing line-window behavior, but enforce:

- default `line_count = retrieval_default_line_count`
- maximum `line_count = retrieval_max_line_count`
- total returned chars no greater than `retrieval_max_chars`
- per-line returned chars no greater than `max_line_chars`

Return metadata with `returned`, `truncated`, `next_line_offset`, and any
`truncated_lines` entries.

### `range_cached_output`

Add a character-range retrieval tool for minified, JSONL, AOF, and other
single-line outputs:

```python
def range_cached_output(
    token: str,
    char_offset: int = 0,
    char_count: int | None = None,
) -> dict:
    """Return a bounded character window from cached output."""
```

If `char_count` is omitted, use `retrieval_max_chars`. Reject negative offsets
and cap requested lengths at `retrieval_max_chars`.

### `query_cached_output`

Keep JMESPath support, but protect the serialized query result with the same
output handling limits. A broad query such as `items` can still be large and
must not bypass the budget.

### `retrieve_cached_output`

Change this tool from "full content by default" to a compatibility alias for
bounded preview retrieval. If callers omit a range or query, return the first
bounded preview plus metadata. If a caller requests unbounded full content,
return an error that points to ranged, queried, or explicit HTTP download
retrieval.

## HTTP and Resource Retrieval

Signed HTTP retrieval should remain available for explicit external processing,
but it should not accidentally load full content into model context.

Recommended behavior:

- `/cache/{token}` with no range or query returns bounded preview metadata, not
  full content.
- `/cache/{token}?line_offset=...&line_count=...` returns a bounded line window.
- `/cache/{token}?char_offset=...&char_count=...` returns a bounded character
  window.
- `/cache/{token}?jmespath=...` returns a bounded query result.
- Full download requires an explicit parameter such as `download=1` or
  `full=1`, and documentation should describe it as intended for external code,
  not for direct model ingestion.
- MCP resource reads should either follow the same bounded default or require an
  explicit full-download variant. The current resource description should stop
  telling clients to read the full output by default.

## Call Path Coverage

Apply `protect_tool_output()` to all externally visible proxy call returns:

- `ToolView.call_tool()` after post-call hooks and before return.
- Custom and composite branches in `ToolView.call_tool()` before returning to
  the client.
- `mcp_proxy.proxy.registration._execute_direct_call()` for root tools when no
  default view exists.
- Search-mode wrappers created by `create_call_tool_wrapper()` through
  `ToolView.call_tool()`.
- Search-per-server wrappers, including the virtual `/search/mcp` view.
- Cache retrieval tools themselves, because retrieval and query results can
  also exceed the inline budget.

The virtual search view should be initialized with the same cache context as
real views.

## Cache Secret Handling

Generate and store a cache secret once per `MCPProxy` instance when
`cache_secret` is not configured. All cache writers, retrieval tools, resources,
and HTTP routes should use that same value. This avoids invalid resource links
caused by multiple random secrets in one process.

## Observability

Record one structured event per protected call:

- `view_name`
- `server_name`
- `tool_name`
- `cache_id`
- `original.bytes`
- `original.estimated_tokens`
- `returned.bytes`
- `returned.estimated_tokens`
- `truncated`
- `truncation_reasons`

For pass-through results, record the same size data with `cached=false` and
`truncated=false`. Debug logging should avoid including full result content.

## Backward Compatibility

This is intentionally a behavior change for oversized output. Small tool
outputs should remain unchanged by default. Existing `output_cache` config keys
should continue to parse.

Expected breaking changes:

- A large result that previously returned in full will now return a cached
  preview envelope.
- `retrieve_cached_output(token)` without a range or query will no longer return
  unbounded full content.
- Tests that assert full retrieval by default need to request `download=1`,
  `range_cached_output`, or a line/query window.

## Test Plan

Unit tests:

- Default config protects a large result without `output_cache` being set.
- Small under-budget results pass through unchanged.
- Over-budget text result returns a `ToolResult` with preview, cache id,
  original sizes, returned sizes, and truncation status.
- A giant single-line result is clipped by `max_line_chars` and exposes
  character-range navigation.
- `preview_cached_output` enforces max line count, total chars, and line length.
- `range_cached_output` returns bounded character windows and rejects invalid
  offsets/counts.
- `query_cached_output` applies output protection to large query results.
- `retrieve_cached_output` no longer returns full content by default.
- Direct registration through `_execute_direct_call()` protects large output.
- Virtual `/search/mcp` `{server}_call_tool` uses the cache context.
- Custom and composite final outputs are protected.
- Generated cache secret is stable across cache writer, retrieval tool,
  resource, and HTTP route registration.

Integration tests:

- Search-per-server `filesystem_call_tool` reading a large file returns an
  inline payload under the default token budget and creates a retrievable cache
  entry.
- A JSONL or minified JSON fixture with one very long line returns a bounded
  preview and can be navigated with `range_cached_output`.
- HTTP `/cache/{token}` defaults to bounded preview, while explicit download
  returns the full cached content.

## Rollout

1. Add the output handling helper and metadata models behind tests.
2. Switch effective output handling defaults to enabled with conservative
   budgets.
3. Wire the helper into view, direct, search, virtual search, custom, composite,
   and cache retrieval paths.
4. Update cache retrieval semantics and add `range_cached_output`.
5. Update documentation examples from opt-in caching to safe default output
   handling.
6. Run `make check` and `make test`.
