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


def _body_excerpt_for(dp) -> str:
    """Cheap body excerpt — read sidecar if present, else empty.

    Used by the relationship classifier to give Haiku enough text
    to judge the relationship type.
    """
    if not dp.storage_key:
        return ""
    try:
        from django.core.files.storage import default_storage
        from donna.core.integrations.bronze import sidecar_key_for

        sidecar = sidecar_key_for(dp.storage_key)
        if not default_storage.exists(sidecar):
            return ""
        with default_storage.open(sidecar, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
        # Drop leading email headers (From:/To:/etc.) to maximise body
        # signal in the truncation window.
        lines = [
            ln for ln in text.splitlines()
            if not ln.startswith(("From:", "To:", "Cc:", "Bcc:", "Subject:", "Date:", "**From:"))
        ]
        return " ".join(lines)[:300]
    except Exception:  # noqa: BLE001
        return ""


# ─── Org relationship reclassification (00m) ─────────────────────────


@shared_task(name="cortex.reclassify_orgs")
def reclassify_orgs(workspace_id: str | None = None, use_llm: bool = True) -> dict:
    """Re-run the relationship classifier ladder over orgs.

    Tier A (rules) → Tier B (Haiku, gated by use_llm).

    - ``workspace_id`` None → every workspace.
    - Skips orgs with ``relationship_locked=True`` (manual override).
    - Always re-derives ``parent_path`` so the vault re-files on next
      render.

    Returns counts: ``{tier_a_decided, tier_b_decided, unchanged,
    skipped_locked}``.
    """
    from collections import defaultdict
    import re

    from donna.cortex.folders import org as org_folder_resolver
    from donna.cortex.models import CortexEntity
    from donna.cortex.relationship_classifier import classify_with_history
    from donna.integrations.models import DeliveryPackage
    from donna.workspaces.models import Workspace

    EMAIL_RE = re.compile(r"[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9\-.]+")

    if workspace_id is not None:
        workspaces = list(Workspace.objects.filter(id=workspace_id))
    else:
        workspaces = list(Workspace.objects.all())

    tier_a = tier_b = unchanged = skipped = 0

    for ws in workspaces:
        primary = ws.primary_domain or ""

        # Build per-domain stats once per workspace
        per_domain: dict[str, dict] = defaultdict(
            lambda: {"senders": set(), "inbound": 0, "outbound": 0, "bodies": []}
        )
        for dp in DeliveryPackage.objects.filter(
            workspace=ws, provider="gmail",
        ).iterator(chunk_size=100):
            canon_ext = (dp.canonical_payload or {}).get("extensions") or {}
            participants = canon_ext.get("participants_emails") or []
            sender_domain = sender_email = None
            to_domains: list[str] = []
            for p in participants:
                if not isinstance(p, dict):
                    continue
                addr_raw = p.get("addr") or ""
                m = EMAIL_RE.search(addr_raw)
                if not m:
                    continue
                addr = m.group(0).lower()
                domain = addr.split("@", 1)[-1]
                role = (p.get("role") or "").lower()
                if role == "from":
                    sender_domain = domain
                    sender_email = addr
                else:
                    to_domains.append(domain)
            if sender_domain and sender_domain != primary:
                d = per_domain[sender_domain]
                d["senders"].add(sender_email)
                d["inbound"] += 1
                # Pull richer signal — DP title + sidecar excerpt
                body_excerpt = _body_excerpt_for(dp)
                d["bodies"].append(
                    f"{dp.title or ''} | {body_excerpt}"[:800]
                )
            if sender_domain == primary:
                for td in set(to_domains):
                    if td != primary:
                        per_domain[td]["outbound"] += 1
                # Outbound emails also contribute body signal — the
                # user's tone toward this org reveals the relationship.
                body_excerpt = _body_excerpt_for(dp)
                for td in set(to_domains):
                    if td != primary:
                        per_domain[td]["bodies"].append(
                            f"[outbound] {dp.title or ''} | {body_excerpt}"[:800]
                        )

        for org in CortexEntity.objects.filter(workspace=ws, type="org"):
            ext = dict(org.extensions or {})
            if ext.get("relationship_locked"):
                skipped += 1
                continue

            domains = ext.get("email_domains") or []
            agg_senders: set[str] = set()
            agg_in = agg_out = 0
            agg_bodies: list[str] = []
            for d in domains:
                stats = per_domain.get(d.lower())
                if stats:
                    agg_senders.update(stats["senders"])
                    agg_in += stats["inbound"]
                    agg_out += stats["outbound"]
                    agg_bodies.extend(stats["bodies"])

            # Tier A
            verdict = classify_with_history(
                org_domain=domains[0] if domains else None,
                workspace_primary_domain=primary,
                sender_emails=list(agg_senders),
                inbound_count=agg_in,
                outbound_count=agg_out,
                body_samples=agg_bodies[:10],
            )

            # Tier B fallback for unknowns
            if verdict.relationship == "unknown" and use_llm:
                from donna.cortex.relationship_classifier_llm import classify_via_llm

                verdict = classify_via_llm(
                    org_title=org.title,
                    org_domains=domains,
                    sender_emails=agg_senders,
                    inbound_count=agg_in,
                    outbound_count=agg_out,
                    body_samples=agg_bodies,
                )
                if verdict.relationship != "unknown":
                    tier_b += 1
            elif verdict.relationship != "unknown":
                tier_a += 1

            old_rel = ext.get("relationship", "unknown")
            if verdict.relationship == old_rel:
                unchanged += 1
                continue

            ext["relationship"] = verdict.relationship
            # Seed multi-label ``roles`` from primary so downstream
            # consumers (vault renderer, agent query, _index.md) can
            # branch uniformly. Manual correction CLI later extends
            # this with additional roles.
            ext["roles"] = [verdict.relationship] if verdict.relationship != "unknown" else []
            ext["relationship_confidence"] = verdict.confidence
            ext["relationship_basis"] = verdict.basis
            ext["relationship_evidence"] = verdict.evidence
            ext["parent_path"] = org_folder_resolver(
                type="org",
                occurred_at=None,
                extensions=ext,
                client_slug=None,
                project_slug=None,
            )
            org.extensions = ext
            org.save(update_fields=["extensions", "updated_at"])

    logger.info(
        "cortex_reclassify_orgs_done",
        extra={
            "tier_a_decided": tier_a,
            "tier_b_decided": tier_b,
            "unchanged":      unchanged,
            "skipped_locked": skipped,
        },
    )
    return {
        "tier_a_decided": tier_a,
        "tier_b_decided": tier_b,
        "unchanged":      unchanged,
        "skipped_locked": skipped,
    }


# ─── Phase 5 vault projection ────────────────────────────────────────


@shared_task(name="cortex.flush_vault_indexes")
def flush_vault_indexes() -> dict:
    """Drain the per-workspace ``vault:dirty:<ws>`` Redis sets and
    regenerate every flagged folder's ``_index.md``.

    Per-entity render + ``_log.md`` append happen synchronously in the
    manager's post-commit hook (cheap); only ``_index.md`` is debounced
    here (it has to re-query all heads for the folder, so it benefits
    from coalescing several writes into one render).

    Uses ``SPOP`` to claim-then-process: another writer that re-dirties
    a folder during render gets picked up on the next flush.
    """
    from donna.cortex.vault_renderer import VaultRenderer

    try:
        from django_redis import get_redis_connection

        redis = get_redis_connection("default")
    except Exception:  # noqa: BLE001
        logger.warning("vault_flush_skip_no_redis")
        return {"workspaces": 0, "folders": 0}

    renderer = VaultRenderer()
    workspace_count = 0
    folder_count = 0

    # Scan all dirty-sets — one per workspace.
    cursor = 0
    keys: list[bytes] = []
    while True:
        cursor, batch = redis.scan(cursor=cursor, match="vault:dirty:*", count=200)
        keys.extend(batch)
        if cursor == 0:
            break

    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        workspace_id = key_str.split(":", 2)[2]
        workspace_count += 1
        # Drain — pop folders one at a time to bound memory; the rare
        # re-dirty during render is caught by the next beat run.
        while True:
            popped = redis.spop(key_str)
            if popped is None:
                break
            folder = popped.decode() if isinstance(popped, bytes) else popped
            try:
                renderer.render_index(workspace_id, folder)
                folder_count += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "vault_flush_index_failed",
                    extra={"workspace_id": workspace_id, "folder": folder},
                )

    if folder_count:
        logger.info(
            "vault_flush_completed",
            extra={"workspaces": workspace_count, "folders": folder_count},
        )
    return {"workspaces": workspace_count, "folders": folder_count}
