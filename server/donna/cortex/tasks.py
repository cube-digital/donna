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
    from donna.cortex.models import CortexEntity

    new_labels = clusterer.recluster(scope)
    if not new_labels:
        return 0

    cluster_to_members: dict[UUID, list[UUID]] = {}
    for entity_id, cluster_id in new_labels.items():
        if cluster_id is None:
            continue
        cluster_to_members.setdefault(cluster_id, []).append(entity_id)

    cluster_names: dict[UUID, str] = {}
    for cluster_id, members in cluster_to_members.items():
        # Bodies live in SilverStorage (P0.14) — fetch lazily; cluster
        # naming reads at most 5 samples per cluster so the cost is small.
        sample_entities = CortexEntity.objects.filter(id__in=members[:5])
        samples = [e.load_body() for e in sample_entities]
        try:
            cluster_names[cluster_id] = namer.name(samples)
        except Exception:  # noqa: BLE001
            logger.exception(
                "cortex_cluster_naming_failed",
                extra={"cluster_id": str(cluster_id)},
            )
            cluster_names[cluster_id] = f"cluster-{cluster_id}"

    updated = 0
    for entity in CortexEntity.objects.filter(id__in=list(new_labels)):
        new_id = new_labels.get(entity.id)
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


@shared_task(name="cortex.recluster_fanout")
def recluster_fanout() -> dict:
    """Beat-scheduled fanout — enqueue one per-workspace job."""
    from donna.workspaces.models import Workspace

    workspace_ids = list(Workspace.objects.values_list("id", flat=True))
    for ws_id in workspace_ids:
        recluster_workspace.delay(str(ws_id))
    return {"enqueued": len(workspace_ids)}


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
