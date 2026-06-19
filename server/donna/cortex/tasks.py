"""
Celery tasks for the Cortex layer.

- ``recluster_workspace`` walks every (client, project) scope inside a
  workspace and runs HDBSCAN per scope. Per spec §6, cluster boundary
  is the ``(workspace_id, client_id, project_id)`` tuple — fanout
  honours that.
- ``recluster_fanout`` enqueues one workspace job per row.
"""
from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task


logger = logging.getLogger(__name__)


@shared_task(name="cortex.recluster_workspace")
def recluster_workspace(workspace_id: str) -> dict:
    """Re-cluster every (client, project) scope inside ``workspace_id``."""
    from donna.cortex.clustering import HDBSCANClusterer, HaikuNamer, Scope
    from donna.cortex.models import CortexEntity

    workspace_uuid = UUID(workspace_id)
    clusterer = HDBSCANClusterer()
    namer = HaikuNamer()

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

    return {
        "workspace_id": workspace_id,
        "reclustered_count": total_updated,
    }


def _recluster_scope(scope, clusterer, namer) -> int:
    """Phase 3 cluster identity continuity (2026-06-15).

    Steps:
      1. Snapshot old centroids + names from existing rows in scope.
      2. HDBSCAN → ``new_labels`` (raw uuid5-minted ids per row).
      3. Compute new centroids per ``new_label``.
      4. Greedy cosine match new → old (threshold 0.80) — matched
         clusters REUSE the old UUID + name, skipping the Haiku call.
      5. Apply remap.

    Result: pure-relabel churn (same docs, shuffled order) preserves
    every UUID and name; a genuine topic split keeps the dominant
    UUID and mints exactly one new one.
    """
    from donna.cortex.models import CortexEntity

    new_labels = clusterer.recluster(scope)
    if not new_labels:
        return 0

    # Step 1 — snapshot old centroids + names from the scope BEFORE
    # remap (rows still carry their pre-recluster cluster_id).
    old_snapshot = _snapshot_old_centroids(scope)

    # Step 2 — bucket rows by their new uuid5-minted cluster_id.
    cluster_to_members: dict[UUID, list[UUID]] = {}
    for entity_id, cluster_id in new_labels.items():
        if cluster_id is None:
            continue
        cluster_to_members.setdefault(cluster_id, []).append(entity_id)

    # Step 3 — compute new centroids from in-scope embeddings.
    new_centroids = _compute_new_centroids(cluster_to_members)

    # Step 4 — greedy continuity match (cosine ≥ 0.80). Matched new
    # clusters REUSE the old UUID + name.
    remap_id, remap_name = _match_centroids(new_centroids, old_snapshot)

    # Step 5 — fill names for unmatched (newly-minted) clusters.
    cluster_names: dict[UUID, str] = dict(remap_name)
    for cluster_id, members in cluster_to_members.items():
        final_id = remap_id.get(cluster_id, cluster_id)
        if final_id in cluster_names:
            continue  # already named via continuity reuse
        sample_entities = CortexEntity.objects.filter(id__in=members[:5])
        samples = [e.load_body() for e in sample_entities]
        try:
            cluster_names[final_id] = namer.name(samples)
        except Exception:  # noqa: BLE001
            logger.exception(
                "cortex_cluster_naming_failed",
                extra={"cluster_id": str(final_id)},
            )
            cluster_names[final_id] = f"cluster-{final_id}"

    # Apply remap to every row.
    updated = 0
    for entity in CortexEntity.objects.filter(id__in=list(new_labels)):
        raw_id = new_labels.get(entity.id)
        new_id = remap_id.get(raw_id, raw_id) if raw_id else None
        new_name = cluster_names.get(new_id) if new_id else None
        ext = dict(entity.extensions or {})
        if entity.cluster_id != new_id or ext.get("cluster_name") != new_name:
            entity.cluster_id = new_id
            ext["cluster_name"] = new_name
            entity.extensions = ext
            entity.save(
                update_fields=["cluster_id", "extensions", "updated_at"]
            )
            updated += 1
    return updated


# ── P3 continuity helpers ──────────────────────────────────────────


_CONTINUITY_COSINE_THRESHOLD = 0.80


def _snapshot_old_centroids(scope) -> dict[UUID, tuple[list[float], str]]:
    """Compute old (cluster_id → centroid, name) from pre-recluster rows."""
    try:
        import numpy as np
    except ImportError:
        return {}
    from donna.cortex.models import CortexEntity

    qs = (
        CortexEntity.objects
        .filter(workspace_id=scope.workspace_id)
        .filter(client_id=scope.client_id)
        .filter(project_id=scope.project_id)
        .filter(doc_embedding__isnull=False, cluster_id__isnull=False)
        .values("cluster_id", "doc_embedding", "extensions")
    )
    buckets: dict[UUID, dict] = {}
    for row in qs:
        cid = row["cluster_id"]
        if cid is None:
            continue
        slot = buckets.setdefault(
            cid,
            {"sum": None, "n": 0, "name": (row.get("extensions") or {}).get("cluster_name", "")},
        )
        vec = np.array(row["doc_embedding"], dtype=np.float32)
        slot["sum"] = vec if slot["sum"] is None else slot["sum"] + vec
        slot["n"] += 1
    out: dict[UUID, tuple[list[float], str]] = {}
    for cid, slot in buckets.items():
        if slot["n"] == 0 or slot["sum"] is None:
            continue
        centroid = (slot["sum"] / slot["n"]).tolist()
        out[cid] = (centroid, slot["name"])
    return out


def _compute_new_centroids(
    cluster_to_members: dict[UUID, list[UUID]],
) -> dict[UUID, list[float]]:
    """Compute new centroids per (new) cluster_id by averaging member embeddings."""
    try:
        import numpy as np
    except ImportError:
        return {}
    from donna.cortex.models import CortexEntity

    out: dict[UUID, list[float]] = {}
    for cluster_id, members in cluster_to_members.items():
        rows = CortexEntity.objects.filter(
            id__in=members, doc_embedding__isnull=False
        ).values_list("doc_embedding", flat=True)
        vecs = list(rows)
        if not vecs:
            continue
        arr = np.array(vecs, dtype=np.float32)
        out[cluster_id] = arr.mean(axis=0).tolist()
    return out


def _match_centroids(
    new_centroids: dict[UUID, list[float]],
    old_snapshot: dict[UUID, tuple[list[float], str]],
) -> tuple[dict[UUID, UUID], dict[UUID, str]]:
    """Greedy cosine match new → old. Returns (remap_id, remap_name)."""
    if not new_centroids or not old_snapshot:
        return {}, {}
    try:
        import numpy as np
    except ImportError:
        return {}, {}

    def _norm(v):
        a = np.array(v, dtype=np.float32)
        return a / max(float(np.linalg.norm(a)), 1e-12)

    old_normed = {oid: (_norm(vec), name) for oid, (vec, name) in old_snapshot.items()}
    new_normed = {nid: _norm(vec) for nid, vec in new_centroids.items()}

    # Score all pairs, sort desc, greedy assign.
    pairs: list[tuple[float, UUID, UUID]] = []
    for nid, nvec in new_normed.items():
        for oid, (ovec, _) in old_normed.items():
            pairs.append((float(np.dot(nvec, ovec)), nid, oid))
    pairs.sort(key=lambda x: -x[0])

    remap_id: dict[UUID, UUID] = {}
    remap_name: dict[UUID, str] = {}
    used_old: set[UUID] = set()
    used_new: set[UUID] = set()
    for score, nid, oid in pairs:
        if score < _CONTINUITY_COSINE_THRESHOLD:
            break
        if nid in used_new or oid in used_old:
            continue
        remap_id[nid] = oid
        remap_name[oid] = old_normed[oid][1]
        used_new.add(nid)
        used_old.add(oid)
    return remap_id, remap_name


@shared_task(name="cortex.recluster_fanout")
def recluster_fanout() -> dict:
    """Beat-scheduled fanout — enqueue one per-workspace job."""
    from donna.workspaces.models import Workspace

    workspace_ids = list(Workspace.objects.values_list("id", flat=True))
    for ws_id in workspace_ids:
        recluster_workspace.delay(str(ws_id))
    return {"enqueued": len(workspace_ids)}


@shared_task(name="cortex.enrich_entity", bind=True, max_retries=2)
def enrich_entity(self, entity_id: str) -> dict:
    """Async enrich (Phase 4c, 2026-06-15) — embed + cluster_assign
    for an entity persisted synchronously by the pipeline.

    Split rationale: the pipeline's sync path persists the row (lint
    + atomic insert + reverse edges) so the write API returns fast.
    Embedding model load + cluster centroid compute can take seconds
    on cold cache; running them async means the user/agent isn't
    blocked. The row is queryable immediately via tsvector + keyword
    channels; dense recall kicks in once enrich completes.
    """
    from donna.cortex.clustering import HDBSCANClusterer, Scope
    from donna.cortex.embeddings import BGESmallEmbedder
    from donna.cortex.models import CortexEntity
    from donna.cortex.registry import TemplateRegistry

    try:
        entity = CortexEntity.objects.get(id=entity_id)
    except CortexEntity.DoesNotExist:
        logger.warning("enrich_entity_missing_row", extra={"entity_id": entity_id})
        return {"entity_id": entity_id, "status": "missing"}

    if entity.doc_embedding is not None:
        return {"entity_id": entity_id, "status": "already_enriched"}

    embedder = BGESmallEmbedder()
    clusterer = HDBSCANClusterer()
    registry = TemplateRegistry()
    try:
        type_spec = registry.get(entity.type)
        body_md = entity.load_body()
        embedding = embedder.embed_entity(
            title=entity.title or "Untitled",
            body_md=body_md,
            sampler=type_spec.embedding_sampler,
        )
        scope = Scope(
            workspace_id=entity.workspace_id,
            client_id=entity.client_id,
            project_id=entity.project_id,
        )
        cluster_id, cluster_name = clusterer.assign(embedding, scope)
    except Exception as exc:  # noqa: BLE001
        logger.exception("enrich_entity_failed", extra={"entity_id": entity_id})
        raise self.retry(exc=exc, countdown=30)

    ext = dict(entity.extensions or {})
    ext["cluster_name"] = cluster_name
    entity.doc_embedding = embedding
    entity.cluster_id = cluster_id
    entity.extensions = ext
    entity.save(update_fields=[
        "doc_embedding", "cluster_id", "extensions", "updated_at",
    ])
    return {
        "entity_id": entity_id,
        "status": "enriched",
        "cluster_id": str(cluster_id) if cluster_id else None,
    }


@shared_task(name="cortex.reap_orphan_bodies")
def reap_orphan_bodies() -> dict:
    """Reap SilverStorage body files whose CortexEntity no longer exists.

    A rare condition: pipeline step 11 wraps body write + entity insert
    in one PG transaction, but if the storage write succeeds and the PG
    commit fails afterwards (rare — connection drop), the body file is
    orphaned. This sweep walks ``cortex/`` under ``default_storage`` and
    deletes any ``<uuid>.md`` that has no matching ``CortexEntity`` row.

    Runs nightly via beat. Idempotent.
    """
    from django.core.files.storage import default_storage

    from donna.cortex.models import CortexEntity

    deleted = 0
    scanned = 0
    try:
        dirs, files = default_storage.listdir("cortex")
    except FileNotFoundError:
        return {"scanned": 0, "deleted": 0}

    # Walk: cortex/<ws>/<type>/<id>.md  — recurse one level via the
    # workspace + type directories.
    for ws_dir in dirs:
        try:
            type_dirs, _ = default_storage.listdir(f"cortex/{ws_dir}")
        except FileNotFoundError:
            continue
        for type_dir in type_dirs:
            try:
                _, body_files = default_storage.listdir(
                    f"cortex/{ws_dir}/{type_dir}"
                )
            except FileNotFoundError:
                continue
            for body_file in body_files:
                scanned += 1
                if not body_file.endswith(".md"):
                    continue
                entity_id = body_file[:-3]  # drop ".md"
                if not CortexEntity.objects.filter(id=entity_id).exists():
                    default_storage.delete(
                        f"cortex/{ws_dir}/{type_dir}/{body_file}"
                    )
                    deleted += 1
    return {"scanned": scanned, "deleted": deleted}
