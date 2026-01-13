# ADR-009: Output Caching and Documentation Restructure

## Status

Accepted

## Context

Two needs emerged from ongoing development:

1. **Large tool outputs**: Tools like `read_file` can return massive outputs (100KB+) that consume valuable LLM context window space. Users needed a way to get previews while allowing generated code to fetch full content.

2. **Documentation complexity**: The README had grown to 532 lines covering every feature. New users found it overwhelming, and there was no clear learning path from basics to advanced features.

Additionally, the memory system was moved to a separate repository for better modularity.

## Key Decisions

### 1. Output Caching System

**Problem**: Large tool outputs waste context window space. An LLM reading a 100KB file loses room for reasoning.

**Solution**: Cache large outputs to disk, return a preview + signed retrieval URL.

**Architecture**:
```
Tool Output → Check Size → If large → Write to /tmp/mcp-proxy-cache/{token}.txt
                                    → Return preview + signed URL
                        → If small → Return full output
```

**Cache response format**:
```json
{
  "cached": true,
  "token": "abc123def456",
  "retrieve_url": "https://proxy.example.com/cache/abc123?expires=1736797800&sig=...",
  "expires_at": "2025-01-13T19:30:00Z",
  "preview": "First 500 characters...",
  "size_bytes": 248000
}
```

**Security model**: Pre-signed URLs (like S3)
- HMAC-SHA256 signature over `{token}:{expires_timestamp}`
- Signature included in URL query params
- URLs expire after configurable TTL (default: 1 hour)
- No authentication required to fetch (signature IS the auth)

**Storage**: `/tmp/mcp-proxy-cache/` directory
- Let OS handle cleanup via normal temp file lifecycle
- No custom garbage collection needed
- Simple and reliable

**Retrieval methods**:
1. `retrieve_cached_output(token)` tool - LLM can pull into context
2. HTTP GET to `retrieve_url` - Generated code can fetch directly
3. Both use the same `verify_and_retrieve()` function

### 2. Configuration Hierarchy

Cache settings can be configured at three levels (most specific wins):

```yaml
# Global default
output_cache:
  enabled: true
  ttl_seconds: 3600
  preview_chars: 500
  min_size: 10000

# Per-server override
mcp_servers:
  filesystem:
    cache_outputs:
      enabled: true
      min_size: 5000

# Per-tool override
    tools:
      read_file:
        cache_output:
          enabled: true
          preview_chars: 1000
```

**Resolution order**: tool → server → global

### 3. HTTP Route Integration

**Problem**: How to serve cache retrieval alongside MCP endpoints?

**Solution**: Discovered the proxy already supports `extra_routes` in `http_app()`:

```python
def http_app(self, extra_routes: list[Route] | None = None) -> Starlette:
```

Cache routes are added automatically when caching is enabled:
- `/cache/{token}` - Retrieve cached output

**Benefit**: Single port, single Tailscale Funnel. No multi-service routing needed.

### 4. Documentation Restructure

**Problem**: 532-line README was overwhelming for new users.

**Solution**: Split into focused documents with clear purposes:

| File | Lines | Purpose |
|------|-------|---------|
| `README.md` | 152 | Quick intro, quickstart, 3 example use cases |
| `docs/index.md` | 103 | Introduction, core concepts, navigation |
| `docs/tutorial.md` | 298 | Step-by-step from install to advanced |
| `docs/use-cases.md` | 365 | Problem → solution format |
| `docs/reference.md` | 732 | Complete feature/CLI reference |

**Key insight**: Organize by user intent:
- "I'm new" → README → Tutorial
- "I have a problem" → Use Cases
- "I need syntax" → Reference

### 5. Memory System Extraction

**Decision**: The memory system (`mcp_memory/`) was extracted to a separate repository.

**New location**: https://github.com/abrookins/easy-mcp-memory

**Rationale**:
- Memory is a distinct concern from proxy functionality
- Separate repos allow independent versioning and releases
- Cleaner dependency tree for users who only need one or the other
- Memory system can evolve with its own roadmap

**Migration**: Users should install `easy-mcp-memory` separately if they need memory functionality.

## Implementation

### New Files
- `mcp_proxy/cache.py` (333 lines) - Core caching logic
- `tests/test_cache.py` - Cache module tests
- `docs/index.md`, `docs/tutorial.md`, `docs/use-cases.md`, `docs/reference.md`

### Modified Files
- `mcp_proxy/models.py` - Added `OutputCacheConfig`, cache fields
- `mcp_proxy/views.py` - Added `CacheContext`, `_apply_caching()`
- `mcp_proxy/proxy/proxy.py` - Cache helpers, route integration, `retrieve_cached_output` tool
- `README.md` - Slimmed to 152 lines

## Consequences

### Positive
- Large outputs no longer consume context (preview only)
- LLM can still access full content when needed
- Documentation has clear learning path
- Memory system can evolve independently
- 100% test coverage maintained

### Trade-offs
- Cache files accumulate in `/tmp` (OS cleanup handles this)
- Requires `cache_secret` and `cache_base_url` for signed URLs
- Memory users need separate package installation

### Future Considerations
- CLI commands for cache management (`mcp-proxy cache serve`, `mcp-proxy cache clear`)
- Cache statistics/monitoring
- Alternative storage backends (Redis, S3)

