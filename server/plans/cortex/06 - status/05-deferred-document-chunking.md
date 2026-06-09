# P0.15 — Document Chunking — SUPERSEDED

**Status:** SUPERSEDED by [`06-p0.15-long-document-support.md`](./06-p0.15-long-document-support.md)
which extends scope to 300+ pages with section tree + tree-walk
retrieval (PageIndex-style).

The deferred plan below is retained for historical context. The
active plan adds:
- `cortex_sections` table (chapter-level embeddings + HaikuFitter
  summaries)
- Three-tier ANN (doc + section + chunk)
- Tree-walk mode for multi-hop reasoning

---

**Status (legacy):** deferred until first long-document client request
**Estimated effort:** ~1.5 days when triggered
**Trigger:** first workspace ingesting a doc > 4000 tokens (~5 pages)

## Why deferred

Current scope cap is **docs ≤ 40 pages**. At that cap, doc-level
embedding (sampled per P0.14) is sufficient for clustering. Retrieval
quality is acceptable because:

- Top-K candidates per question (vector ANN over doc-level embeddings)
- LLM synthesis loads the **full body** of top hits into context
- 40-page doc ≈ 30k tokens → fits in modern LLM context windows
  (Sonnet 200k, Haiku 200k)

Chunking adds complexity (new table, new write-path step, new query
flow) that isn't justified until docs exceed the 40-page cap or
workspaces require sub-document navigation.

## What chunking will add when needed

Per [`../04 - flows/04-clustering-online-vs-batch.md`](../04%20-%20flows/04-clustering-online-vs-batch.md)
plus session discussion:

| Tier | Storage | Use |
|---|---|---|
| **1. Doc-level embedding** | `cortex_entities.doc_embedding` | clustering + topical routing |
| **2. Chunk-level embedding** | new `cortex_chunks` table | needle-in-haystack retrieval inside long docs |

Section-tier (chapter-level embeddings) was discussed and rejected for
the ≤40-page cap — `section_path` denormalised as a string on each
chunk row covers the case.

## Proposed schema (locked when phase activates)

```python
class CortexChunk(TimestampsMixin):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4)
    entity          = models.ForeignKey(
        "cortex.CortexEntity",
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_idx       = models.IntegerField()
    byte_start      = models.IntegerField()
    byte_end        = models.IntegerField()
    section_path    = models.CharField(max_length=500, blank=True, default="")
    token_count     = models.IntegerField()
    chunk_embedding = VectorField(dimensions=384)
    text_preview    = models.CharField(max_length=500, blank=True, default="")
    # No chunk body field — load from SilverStorage entity.body[byte_start:byte_end]

    class Meta:
        db_table = "cortex_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "chunk_idx"],
                name="uq_chunk_entity_idx",
            ),
        ]
        indexes = [
            models.Index(fields=["entity", "chunk_idx"]),
        ]
```

Plus `CREATE INDEX cortex_chunks_emb_ivf USING ivfflat (chunk_embedding vector_cosine_ops) WITH (lists = 100)`.

## Chunking strategy

Section-aware sliding-window tokeniser:

```python
def section_aware_chunk(body_md, *, max_tokens=400, overlap_tokens=50):
    sections = parse_markdown_sections(body_md)  # H1/H2/H3 boundaries via markdown-it
    chunks = []
    for section in sections:
        if section.token_count <= max_tokens:
            chunks.append(Chunk(from section))
        else:
            for window in slide(section.tokens, max_tokens, overlap_tokens):
                chunks.append(Chunk(from window))
    return chunks
```

## TypeSpec hooks (already designed in P0.14)

```python
@dataclass(frozen=True)
class TypeSpec:
    ...
    chunk_strategy: ChunkStrategy | None = None    # None = no chunks
    chunk_threshold_tokens: int = 4000             # below this = no chunks
```

P0.14 sets these to defaults (None / 4000) so P0.15 just turns them
on per type.

## Pipeline integration

Step 5 extends:

```python
if cortex_type == "doc" and len(body_md) > type_spec.chunk_threshold_bytes:
    chunks = type_spec.chunk_strategy(body_md)
    chunk_embeddings = embedder.embed_batch([c.text for c in chunks])
    doc_embedding = embedder.embed_entity(
        title=dp.title, body_md=body_md, sampler=type_spec.embedding_sampler,
    )
else:
    chunks = []
    doc_embedding = embedder.embed_entity(
        title=dp.title, body_md=body_md, sampler=type_spec.embedding_sampler,
    )
```

Step 11 inserts chunks alongside the entity in the same atomic block:

```python
with transaction.atomic():
    new_entity.save()
    new_entity.body.save(...)              # body file
    if chunks:
        CortexChunk.objects.bulk_create([
            CortexChunk(
                entity=new_entity, chunk_idx=i,
                byte_start=c.byte_start, byte_end=c.byte_end,
                section_path=c.section_path,
                token_count=c.token_count,
                chunk_embedding=chunk_embeddings[i],
                text_preview=c.text[:500],
            )
            for i, c in enumerate(chunks)
        ])
    # reverse-edge updates
```

## Read API extension

`cortex.search` gains chunk-level ANN:

```
POST /cortex/v1/search
{
  "workspace_id": "...",
  "query": "warranty period",
  "scope": {...},
  "top_k": 10,
  "search_chunks": true
}
```

Response includes top-K chunks (across all docs) with parent entity
metadata.

Client loads chunk text via byte-range read of `entity.body`:

```python
def load_chunk_text(entity, chunk):
    with entity.body.open("rb") as f:
        f.seek(chunk.byte_start)
        return f.read(chunk.byte_end - chunk.byte_start).decode("utf-8")
```

## Cost analysis (when triggered)

Per 40-page doc ingest:
- ~80 chunks at 400 tokens each
- 80 BGE-small embed calls × 5ms = ~400ms
- 80 row inserts (bulk) = ~100ms
- Storage: 80 × 384 × 4 = ~120 KB per doc in PG
- **Total marginal cost: <1s per 40-page doc**

Per question (long-doc retrieval):
- 1 question embedding
- 2 ANN searches (doc-level + chunk-level)
- 5-10 byte-range reads from S3 (parallel)
- 1 LLM synthesis
- **Total: <3s**

## When to activate

| Trigger | Action |
|---|---|
| First workspace ingests a doc > 4000 tokens | Activate P0.15 — schema + pipeline + read API |
| Multiple workspaces report "agent missed answer in long doc" | Activate P0.15 |
| Cap raised above 40 pages | Activate P0.15 + plan P0.15.5 (section tier) |
| Until trigger | **Stay deferred. Ship P0.14 first.** |

## Phase ordering

```
P0.14 (ship now)     → body to FileField + sampled embedding
P0.15 (defer)        → cortex_chunks table + chunking pipeline + chunk ANN
P0.15.5 (post-v1)    → cortex_sections table (chapter navigation)
```

## Anti-patterns to avoid

| Don't | Reason |
|---|---|
| Build chunks for every type | chat/email/meeting fit in single vector; chunks pure overhead |
| Build chunks for short docs | <4000 tokens = single-vector wins on simplicity |
| Build a separate `cortex_sections` table now | denormalised `section_path` string on chunk row covers the case for ≤40-page docs |
| Pre-emptively chunk at write before threshold check | wastes embed calls; threshold gate is cheap |
| Use chunk-only retrieval without doc-level | loses topical context; doc-level routing reduces ANN search space 10× |

## What this defers cleanly

Because TypeSpec already carries `chunk_strategy` + `chunk_threshold_tokens`
(defaulted to None / 4000 in P0.14), activating P0.15 means:

1. Add `cortex_chunks` table + migration
2. Implement `chunking.py` (section-aware tokeniser)
3. Set per-type `chunk_strategy` for `doc:*` types
4. Update Pipeline step 5 + step 11
5. Add chunk-level branch to read API
6. Tests

No retroactive change to existing TypeSpecs or rows. Existing rows
stay single-vector forever (unless re-ingested under a new
`chunk_strategy`).
