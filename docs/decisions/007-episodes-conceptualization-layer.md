# ADR-007: Episodes as Conceptualization Layer

## Status

Accepted

## Context

The memory system (ADR-004) stores raw conversation data in Threads and extracted knowledge in Concepts. However, there's a gap between these two layers:

1. **Threads are ephemeral** — They capture raw messages but aren't structured for knowledge extraction
2. **Concepts are disconnected from source** — No way to trace which conversations knowledge came from
3. **Reprocessing is difficult** — Can't revisit old conversations with updated conceptualization strategies

This ADR introduces Episodes as an intermediate layer that bridges raw experience and conceptualized knowledge.

## Key Decisions

### 1. Three-Layer Architecture

**Problem**: Direct Thread → Concept extraction loses context and prevents reprocessing.

**Solution**: Introduce a three-layer architecture:

```
Raw Experience (Thread) → Episode → Concepts
```

- **Thread**: Raw messages with full conversation context
- **Episode**: Objective record of what happened, with temporal boundaries and metadata
- **Concept**: Extracted knowledge that can be reused

**Rationale**: Episodes serve as a stable intermediate representation. When conceptualization strategies improve, episodes can be reprocessed without re-reading raw threads.

### 2. Episode ↔ Thread: 1:1 Relationship

**Problem**: Should episodes span multiple threads, or map 1:1?

**Decision**: Each Episode derives from exactly one Thread.

**Implementation**:
- Thread has `episode_id` field linking to its derived episode
- Thread has `processing_status` field: `pending` | `processing` | `completed`
- Episode has `source_thread_id` field pointing back to the source

**Rationale**: 1:1 mapping keeps the relationship simple and traceable. Threads that span multiple sessions can still produce one episode per session if needed.

### 3. Episode ↔ Concept: Bidirectional Links

**Problem**: Need to trace concept provenance and enable episode reprocessing.

**Decision**: Maintain bidirectional links between Episodes and Concepts.

**Implementation**:
- Episode has `concept_ids: list[str]` — concepts derived from this episode
- Concept has `episode_ids: list[str]` — episodes that contributed to this concept
- `link_episode_to_concept()` tool updates both sides atomically

**Rationale**: Bidirectional links enable:
- Forward: "What concepts came from this experience?"
- Backward: "Where did this knowledge originate?"
- Reprocessing: Update concept links when re-analyzing episodes

### 4. Flat Hierarchy (No Nesting)

**Problem**: Should episodes support hierarchical organization like Concepts?

**Decision**: Episodes use flat storage like Reflections.

**Rationale**: Episodes are time-bounded records, not knowledge structures. Hierarchical organization doesn't add value—temporal and project-based filtering is sufficient.

### 5. Client-Side Intelligence

**Problem**: Should the MCP server perform conceptualization automatically?

**Decision**: The MCP server provides primitives only. Conceptualization logic lives in the client (LLM).

**Tools provided**:
- `upsert_episode` — Create/update episodes
- `get_episode` — Retrieve by ID
- `find_episodes` — List or semantic search
- `link_episode_to_concept` — Create bidirectional links
- `get_pending_threads` — Discover threads awaiting processing
- `mark_thread_status` — Manual status control

**Rationale**: Different LLMs may have different conceptualization strategies. Keeping the server "dumb" maintains flexibility and avoids server-side LLM dependencies.

### 6. Episode Model Fields

**Temporal boundaries**:
- `started_at`, `ended_at` — When the experience occurred
- `timezone` — Optional timezone context

**Contextual metadata**:
- `platform` — Where it happened (e.g., "claude", "chatgpt")
- `source_title` — Human-readable title
- `client`, `model` — Technical context
- `voice_mode`, `input_modalities`, `output_modalities` — Interaction mode
- `qualities` — Extensible dict for additional metadata

**Links**:
- `source_thread_id` — The thread this was derived from
- `concept_ids` — Concepts extracted from this episode

**Content**:
- `events` — Markdown body with timestamped narration

## Consequences

- Clear provenance chain from raw conversation → episode → concepts
- Episodes can be reprocessed as conceptualization improves
- Thread processing workflow: `pending` → `processing` → `completed`
- Semantic search works across episodes (title, events, tags)
- No server-side LLM dependency—client controls all intelligence
- 100% test coverage maintained with 38 new episode-related tests

