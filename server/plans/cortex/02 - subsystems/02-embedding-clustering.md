# Subsystem 2 — Embedding + Clustering

**Concern:** group entities by latent topic so navigation emerges from
the data rather than hand-curated folders.

## Plain English

A meeting about Stripe integration and an email about Stripe API
quotas are about the same thing — but they live in different bronze
sources, use different vocabulary, and have totally different
metadata. The only way to know they're related is to LOOK AT THE
TEXT.

We do that by:

1. **Embedding** — turn each body_md into a 384-dimensional vector.
   Vectors with close cosine similarity = text with similar meaning.
2. **Clustering** — group vectors into clusters using HDBSCAN.
3. **Naming** — ask Anthropic Haiku for a 2-4 word name per cluster
   given 5 sample texts.

End result: every row has a `cluster_id` (UUID) + `cluster_name`
(human-readable). The folder for content-shaped types
(note/clip/file) becomes `01 - Clusters/<cluster_name>/`.

## Embedding

### Default — `BGESmallEmbedder`

```python
class BGESmallEmbedder:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        normalize: bool = True,
    ): ...
    def embed(self, text: str) -> list[float]: ...   # 384-dim
    def embed_entity(
        self,
        title: str,
        body_md: str,
        sampler: Callable[[str, str], str] | None = None,
    ) -> list[float]: ...                            # applies sampler before embed
```

- Local inference (sentence-transformers + torch)
- 384 dimensions (small + fast vs 768/1536 alternatives)
- L2-normalised → cosine similarity == dot product

### Sampled input (P0.14)

BGE-small max context = 512 tokens ≈ ~1900 chars EN. We DO NOT send
the full body to the embedder — instead a **sampled representation**
(default `fixed_window_sampler`):

```
title         (~100 chars)   identity anchor
intro         (~700 chars)   what this is
middle        (~600 chars)   what's discussed (centered)
tail          (~500 chars)   decisions / conclusion / signatures
```

Per-type override via `TypeSpec.embedding_sampler`. Cheat-sheet:

| Type | Sampler | Why |
|---|---|---|
| chat, email, ticket | `head_heavy_sampler` | latest message / issue summary first |
| meeting, runbook | `uniform_sampler` | content distributed |
| doc | `head_tail_sampler` | intro + signatures/addendums |
| clip, note, person, org, project, concept, decision | `fixed_window_sampler` (default) | unknown shape or short |

See [`P0.14 plan`](../06%20-%20status/04-p0.14-storage-and-embedding-refactor.md)
for the full plan. For documents above ~4000 tokens, additional
chunk-level embeddings are **deferred** to P0.15 — see
[`05-deferred-document-chunking.md`](../06%20-%20status/05-deferred-document-chunking.md).

### Why 384

| Dim | Storage per row | ANN speed | Quality |
|---|---|---|---|
| 384 (BGE-small) | 1.5 KB | fast | good |
| 768 (BGE-base) | 3 KB | medium | better |
| 1536 (OpenAI text-embedding-3-small) | 6 KB | slower | similar |

384 is the sweet spot: BGE-small is open-weight, runs on CPU, holds up
on STS-B benchmarks. Postgres `vector(384)` with IVFFLAT index handles
millions of rows.

### Alternative — `OpenAIEmbedder`

Drop-in Strategy. Workspaces with a flag in `extensions/typespecs/`
can opt into hosted embeddings. Same pipeline.

### Lazy loading

```python
def _load(self):
    if self._model is None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)
    return self._model
```

PyTorch + sentence-transformers add ~2GB to the venv. Lazy import
means Django processes that don't actually call `embed()` don't pay
the cost.

## Clustering

### Default — `HDBSCANClusterer`

Two operations, very different cost:

| Operation | Trigger | Cost |
|---|---|---|
| `assign(embedding, scope)` | every write | O(clusters in scope) — fast |
| `recluster(scope)` | nightly Celery beat | O(N²) — expensive |

### Online assign (write path)

```python
def assign(self, embedding, scope) -> tuple[UUID | None, str | None]:
    centroids = self._compute_centroids(scope)  # mean vector per cluster
    if not centroids:
        return None, None                       # cold start

    # cosine = dot product (vectors are unit-normalised)
    best = max(
        centroids.items(),
        key=lambda kv: dot(embedding, kv[1].centroid),
    )
    return best.id, best.name
```

Cheap because:
- Embeddings are pre-normalised → cosine = dot product
- Centroids computed per-scope from previous rows (small in practice)
- For workspaces with many entities, snapshot centroids to a
  `cortex_centroid` cache table (post-v1)

### Batch recluster (nightly)

```python
def recluster(self, scope) -> dict[UUID, UUID | None]:
    rows = scoped_queryset(scope).values_list("id", "doc_embedding")
    embeddings = np.array([r[1] for r in rows])

    labels = hdbscan.HDBSCAN(
        min_cluster_size=5,
        metric="cosine",
    ).fit_predict(embeddings)

    # -1 = noise → no cluster
    # 0, 1, 2, ... = cluster integer label → mapped to stable UUID
    ns = uuid5(NAMESPACE_URL, f"cortex-cluster:{scope_tuple}")
    return {
        id: (None if label == -1 else uuid5(ns, str(label)))
        for id, label in zip(ids, labels)
    }
```

Why HDBSCAN:

| Property | HDBSCAN | K-Means |
|---|---|---|
| Need k upfront | ❌ no | ✅ yes |
| Variable density | ✅ handles | ❌ blocks |
| Noise detection | ✅ -1 label | ❌ forces all into clusters |
| Hierarchy | ✅ | ❌ |

Workspaces start tiny; topics emerge over time. K-Means would force
arbitrary k. HDBSCAN finds clusters as they crystallise.

Cluster UUIDs are deterministic via `uuid5(namespace, integer_label)`
so:
- the cluster keeps its UUID across reclusters
- `data.cluster_id` references survive nightly rebuilds

### Tuning knobs

| Param | Default | Notes |
|---|---|---|
| `min_cluster_size` | 5 | smaller = more clusters; raise for noisy workspaces |
| `metric` | `cosine` | matches IVFFLAT index |
| `embedding_dim` | 384 | matches `vector(384)` column |

## Naming

### `HaikuNamer`

```python
class HaikuNamer:
    DEFAULT_MODEL = "anthropic/claude-3-5-haiku-latest"
    DEFAULT_PROMPT = (
        "Given the following short text excerpts from documents that "
        "share a latent topic, propose a 2-4 word descriptive name "
        "for the topic. Output ONLY the name, nothing else.\n\n"
    )

    def name(self, sample_texts: list[str]) -> str:
        # 5 samples × first 500 chars each → Haiku → name string
        ...
```

Runs only at recluster time (nightly), once per cluster. Each
workspace pays a handful of cents per night.

## ClusteringService — the composition

```python
class ClusteringService:
    def __init__(self, embedder, clusterer, namer): ...

    def assign(self, *, body_md, scope):
        embedding = self._embedder.embed(body_md)
        cluster_id, cluster_name = self._clusterer.assign(embedding, scope)
        return embedding, cluster_id, cluster_name
```

The writer calls `assign(body_md, scope)` once per row in step 5.

## Tasks (Celery beat)

```python
@shared_task(name="cortex.recluster_fanout")
def recluster_fanout():
    for ws_id in Workspace.objects.values_list("id", flat=True):
        recluster_workspace.delay(str(ws_id))

@shared_task(name="cortex.recluster_workspace")
def recluster_workspace(workspace_id):
    # iterate every (client, project) scope in workspace
    # recluster + rename each
```

Beat schedule (`donna/settings.py`):

```python
"cortex-recluster-fanout": {
    "task": "cortex.recluster_fanout",
    "schedule": env.int("DONNA_CORTEX_RECLUSTER_INTERVAL", default=86400),
}
```

Default: nightly. Big workspaces should bump to weekly.

## Why clustering at all

Without clusters:
- folders are hand-curated → drift, inconsistency
- agent search has no topical lens → relies purely on entity_refs
- new topics appear but nobody renames anything

With clusters:
- folder emerges from data
- `data.cluster_name` becomes a navigation handle
- agent can ask "show me everything in 'Customer Onboarding'" without
  knowing the names of customers

Plus the embedding column gives free ANN search (cortex_entity_doc_emb_ivf)
for "find me similar entities" — used by R7 contradiction detection
(post-v1) and by the agent's retrieval layer.

## Failure modes

| Failure | Behaviour |
|---|---|
| `sentence-transformers` not installed | `ImportError` at first `embed()` call |
| `hdbscan` not installed | `ImportError` at `recluster()` |
| Cold workspace (no clusters yet) | `assign` returns `(None, None)`; row gets no cluster until recluster runs |
| Cluster naming LLM error | logged + fallback to `cluster-<id>` |
| Noise points (HDBSCAN -1) | `cluster_id = None` — appears in "Unsorted" folder |
