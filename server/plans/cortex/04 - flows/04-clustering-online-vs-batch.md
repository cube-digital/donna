# Clustering — Online vs Batch

Two cluster operations, very different costs and very different roles.

| Operation | When | Cost | Cardinality |
|---|---|---|---|
| `assign(embedding, scope)` | every write | O(C) where C = clusters in scope | per row |
| `recluster(scope)` | nightly Celery beat | O(N²) where N = rows in scope | per scope |

## Online assign (write path)

Triggered: every `CortexWriter.write(dp)` step 5.

```python
def assign(self, embedding, scope) -> tuple[UUID | None, str | None]:
    centroids = self._compute_centroids(scope)
    if not centroids:
        return None, None                       # cold start

    emb = normalise(embedding)
    best = max(
        centroids.items(),
        key=lambda kv: cosine(emb, kv[1].centroid),
    )
    return best.id, best.name
```

**Cheap because:**

1. Embeddings are pre-normalised → cosine = dot product
2. Centroids computed per-scope from previous rows (small in practice
   — usually 5-50 clusters per scope)
3. Single pass through centroids, O(C × 384) flops

**No `min_cluster_size` enforced at assign time** — the row gets
matched to the closest centroid even if it's far. The nightly
recluster can later move it to "noise" (cluster_id = NULL) if it
doesn't belong.

## Batch recluster (nightly)

Triggered: Celery beat → `tasks.recluster_fanout` →
per-workspace `recluster_workspace`.

```python
@shared_task(name="cortex.recluster_workspace")
def recluster_workspace(workspace_id: str) -> dict:
    workspace_uuid = UUID(workspace_id)
    clusterer = HDBSCANClusterer()
    namer = HaikuNamer()

    # Iterate every (client, project) scope in workspace
    scopes = (
        CortexEntity.objects.filter(workspace_id=workspace_uuid)
        .values_list("client_id", "project_id")
        .distinct()
    )
    total_updated = 0
    for client_id, project_id in scopes:
        scope = Scope(
            workspace_id=workspace_uuid,
            client_id=client_id,
            project_id=project_id,
        )
        total_updated += _recluster_scope(scope, clusterer, namer)
    return {"workspace_id": workspace_id, "reclustered_count": total_updated}
```

For each scope:

```python
def recluster(self, scope) -> dict[UUID, UUID | None]:
    rows = self._scoped_queryset(scope).filter(doc_embedding__isnull=False)
                                       .values_list("id", "doc_embedding")
    embeddings = np.array([r[1] for r in rows])

    labels = hdbscan.HDBSCAN(
        min_cluster_size=5,
        metric="cosine",
    ).fit_predict(embeddings)

    # Map integer labels → deterministic UUIDs
    ns = uuid5(NAMESPACE_URL, f"cortex-cluster:{scope_tuple}")
    return {
        id: (None if label == -1 else uuid5(ns, str(label)))
        for id, label in zip(ids, labels)
    }
```

After clustering, name each non-noise cluster from 5 sample texts:

```python
for cluster_id, members in cluster_to_members.items():
    samples = list(
        CortexEntity.objects.filter(id__in=members[:5]).values_list("body_md", flat=True)
    )
    try:
        cluster_names[cluster_id] = namer.name(samples)
    except Exception:
        cluster_names[cluster_id] = f"cluster-{cluster_id}"
```

Then write back each entity whose cluster changed:

```python
for entity in CortexEntity.objects.filter(id__in=list(new_labels)):
    new_id = new_labels.get(entity.id)
    new_name = cluster_names.get(new_id) if new_id else None
    ext = dict(entity.extensions or {})
    if entity.cluster_id != new_id or ext.get("cluster_name") != new_name:
        entity.cluster_id = new_id
        ext["cluster_name"] = new_name
        entity.extensions = ext
        entity.save(update_fields=["cluster_id", "extensions", "updated_at"])
```

## Why two modes, not one

| Choice | Why not |
|---|---|
| Online HDBSCAN per write | HDBSCAN is O(N log N) — running it per write is O(N) → quadratic over time |
| Batch only | New rows get no cluster until next nightly run → no folder for hours |
| **Online assign + nightly batch** | best of both: fast write, accurate clustering |

## Cluster identity persistence

Cluster IDs are deterministic UUIDs via:

```python
ns = uuid5(NAMESPACE_URL, f"cortex-cluster:{workspace}:{client}:{project}")
cluster_id = uuid5(ns, str(integer_label))
```

This means:

- Same scope + same HDBSCAN integer label → same UUID across reclusters
- `data.cluster_id` references survive nightly rebuilds
- Cluster names get updated, but the id stays — agents can pin to a
  cluster reliably

(Caveat: HDBSCAN's integer label assignment can shift if the dataset
changes drastically. In practice this is rare; if it happens the
cluster keeps the name but gets a new UUID.)

## Scope respect

```python
def _scoped_queryset(self, scope: Scope):
    qs = CortexEntity.objects.filter(workspace_id=scope.workspace_id)
    qs = qs.filter(client_id=scope.client_id) if scope.client_id else qs.filter(client_id__isnull=True)
    qs = qs.filter(project_id=scope.project_id) if scope.project_id else qs.filter(project_id__isnull=True)
    return qs
```

A meeting in `(ws-qube, acme, onboarding)` only sees clusters in that
exact scope. Acme content can never join Stripe content's cluster.

## Embedding model

Default `BGESmallEmbedder` (`BAAI/bge-small-en-v1.5`, 384-dim, local).

Alternative `OpenAIEmbedder` (`text-embedding-3-small`, 1536-dim,
hosted) registered behind a workspace flag.

Both implement `EmbeddingStrategy.embed(text) → list[float]`. Same
ANN index (IVFFLAT on `doc_embedding`).

## Cluster naming via Haiku

`HaikuNamer` takes 5 samples per cluster (each truncated to 500 chars)
and asks Anthropic Haiku for a 2-4 word name:

```
prompt = """
Given the following short text excerpts from documents that share a
latent topic, propose a 2-4 word descriptive name for the topic.
Output ONLY the name, nothing else.

Excerpt 1:
[500 chars from sample 1]

---

Excerpt 2:
[500 chars from sample 2]

...
"""
```

Cost per workspace per night: ~$0.01-0.05 for typical workspace sizes.
A workspace with 100 clusters pays ~100 Haiku calls (each capped at
hundreds of tokens).

## Beat schedule

```python
# donna/settings.py
CELERY_BEAT_SCHEDULE = {
    "cortex-recluster-fanout": {
        "task": "cortex.recluster_fanout",
        "schedule": env.int("DONNA_CORTEX_RECLUSTER_INTERVAL", default=86400),  # 24h
    },
}
```

Daily by default. Big workspaces can lift to weekly via env var.

## When online assign returns None

Cold start: no clusters exist yet. The new row gets `cluster_id =
None`, `cluster_name = None`. It floats unclustered until the next
recluster run creates clusters around it (needs ≥ 5 rows per
`min_cluster_size`).

`ClusterFolderResolver` handles None gracefully:

```python
def canonical_path(self, *, extensions, ...):
    name = extensions.get("cluster_name") or "unsorted"
    return f"{self._base}/{name}"
```

→ unclustered rows live in `01 - Clusters/unsorted/` until the next
nightly run promotes them.

## Why HDBSCAN

| Property | HDBSCAN | K-Means | DBSCAN |
|---|---|---|---|
| Need k upfront | ❌ | ✅ | ❌ |
| Variable density | ✅ | ❌ | ⚠️ |
| Noise detection | ✅ | ❌ | ✅ |
| Hierarchy | ✅ | ❌ | ❌ |
| Robust to outliers | ✅ | ❌ | ⚠️ |

Workspaces start tiny; topics emerge over time. K-Means would force
arbitrary k. HDBSCAN finds clusters as they crystallise + flags noise.

## Tuning knobs

| Param | Default | When to change |
|---|---|---|
| `min_cluster_size` | 5 | larger workspaces want >5 for tighter clusters |
| `metric` | `cosine` | matches IVFFLAT index, don't change |
| `embedding_dim` | 384 | matches `vector(384)` column, don't change |
| Recluster interval | 86400s (24h) | weekly for large workspaces |
| Haiku name temperature | 0.2 | higher for more creative names |

## Failure modes

| Failure | Behaviour |
|---|---|
| HDBSCAN not installed | Online assign returns `(None, None)`; nightly recluster raises ImportError |
| Cold workspace (no clusters yet) | `assign` returns `(None, None)`; row gets no cluster |
| Cluster naming LLM error | logged + fallback to `cluster-<id>` |
| Noise points (HDBSCAN -1 label) | `cluster_id = None` — "unsorted" folder |
| All embeddings identical | HDBSCAN collapses to 1 cluster |
