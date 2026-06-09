"""
``manage.py cortex_sync`` — Postgres-as-derived-index maintenance.

Spec §14 promise: Postgres is dispensable. ``cortex_sync`` is the
operator-facing tool that keeps the derived index aligned with the
canonical files in SilverStorage.

Subcommands (mix and match via flags):

- ``--reindex-embeddings``  recompute ``doc_embedding`` for rows
                            where it's NULL (or where ``--force``
                            requests a rebuild).
- ``--rebuild-clusters``    re-run HDBSCAN per scope and update
                            ``cluster_id`` / ``cluster_name``.
- ``--reap-orphans``        delete SilverStorage body files that no
                            longer match a CortexEntity row.
- ``--rebuild``             FULL rebuild from files (Postgres truncate
                            + walk SilverStorage). Limited in v1 —
                            see "Limitations" below.

Scope:

- ``--workspace <slug-or-uuid>``  restrict to one workspace.
- (else all workspaces)

Limitations of ``--rebuild`` in v1:
The current Jinja templates emit only display-grade frontmatter
(title, occurred_at, parent_path, slug, type extensions). They do
NOT carry sources/applied_in/contradicts/content_hash/cluster_id/
client_id/project_id. A full files-as-truth rebuild therefore
recovers only display fields. Edge data and provenance live in PG
until templates ship full frontmatter (planned post-P10 vault
projection).

The ``--rebuild`` flag currently raises ``NotImplementedError`` to
keep the operator from silently losing edge data. Use
``--reindex-embeddings`` + ``--rebuild-clusters`` + ``--reap-orphans``
to keep the index hot meanwhile.
"""
from __future__ import annotations

import logging
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Cortex derived-index maintenance. Supports embedding reindex, "
        "cluster rebuild, orphan file reaping, and (stub) full rebuild."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            help="Restrict to one workspace (slug or UUID).",
            default=None,
        )
        parser.add_argument(
            "--reindex-embeddings",
            action="store_true",
            help="Recompute doc_embedding for rows with NULL embedding.",
        )
        parser.add_argument(
            "--rebuild-clusters",
            action="store_true",
            help="Re-run HDBSCAN per scope; update cluster_id + cluster_name.",
        )
        parser.add_argument(
            "--reap-orphans",
            action="store_true",
            help="Delete SilverStorage body files orphaned from PG.",
        )
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help=(
                "FULL rebuild from files. Limited in v1 — see "
                "module docstring. Currently raises."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="With --reindex-embeddings: rebuild ALL rows, not just NULLs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts; don't write.",
        )

    def handle(self, *args, **opts):
        if not any(
            opts[flag]
            for flag in (
                "reindex_embeddings",
                "rebuild_clusters",
                "reap_orphans",
                "rebuild",
            )
        ):
            raise CommandError(
                "Pick at least one of --reindex-embeddings / "
                "--rebuild-clusters / --reap-orphans / --rebuild."
            )

        workspace_ids = self._resolve_workspaces(opts.get("workspace"))

        report: dict[str, object] = {}

        if opts.get("reindex_embeddings"):
            report["embeddings"] = self._reindex_embeddings(
                workspace_ids,
                force=opts.get("force", False),
                dry_run=opts.get("dry_run", False),
            )

        if opts.get("rebuild_clusters"):
            report["clusters"] = self._rebuild_clusters(
                workspace_ids,
                dry_run=opts.get("dry_run", False),
            )

        if opts.get("reap_orphans"):
            report["orphans"] = self._reap_orphans(opts.get("dry_run", False))

        if opts.get("rebuild"):
            raise CommandError(
                "--rebuild is not implemented in v1. Current Jinja "
                "templates emit display-grade frontmatter only; full "
                "files-as-truth reconstruction would silently drop "
                "edge data and provenance. Ship full frontmatter via "
                "the Mode A vault projection (P10) before enabling this."
            )

        self.stdout.write(self.style.SUCCESS(f"cortex_sync done: {report}"))

    # ── workspace resolution ───────────────────────────────────────

    def _resolve_workspaces(self, workspace_arg: str | None) -> list[UUID]:
        from donna.workspaces.models import Workspace

        if workspace_arg is None:
            return list(Workspace.objects.values_list("id", flat=True))

        try:
            ws_uuid = UUID(workspace_arg)
            return [ws_uuid] if Workspace.objects.filter(id=ws_uuid).exists() else []
        except (ValueError, TypeError):
            ws = Workspace.objects.filter(slug=workspace_arg).first()
            if ws is None:
                raise CommandError(
                    f"No workspace matches {workspace_arg!r} (slug or UUID)."
                )
            return [ws.id]

    # ── reindex embeddings ─────────────────────────────────────────

    def _reindex_embeddings(
        self,
        workspace_ids: list[UUID],
        *,
        force: bool,
        dry_run: bool,
    ) -> dict:
        from donna.cortex.embeddings import BGESmallEmbedder
        from donna.cortex.models import CortexEntity
        from donna.cortex.registry import TemplateRegistry

        embedder = BGESmallEmbedder()
        registry = TemplateRegistry()

        qs = CortexEntity.objects.filter(workspace_id__in=workspace_ids)
        if not force:
            qs = qs.filter(doc_embedding__isnull=True)

        total = qs.count()
        if dry_run:
            return {"would_update": total}

        updated = 0
        for entity in qs.iterator(chunk_size=200):
            try:
                spec = registry.get(entity.type)
            except KeyError:
                continue
            body_md = entity.load_body()
            if not body_md:
                continue
            try:
                entity.doc_embedding = embedder.embed_entity(
                    title=entity.title or "",
                    body_md=body_md,
                    sampler=spec.embedding_sampler,
                )
                entity.save(update_fields=["doc_embedding", "updated_at"])
                updated += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "cortex_sync_reindex_failed",
                    extra={"entity_id": str(entity.id)},
                )
        return {"updated": updated, "candidates": total}

    # ── rebuild clusters ───────────────────────────────────────────

    def _rebuild_clusters(
        self,
        workspace_ids: list[UUID],
        *,
        dry_run: bool,
    ) -> dict:
        if dry_run:
            return {"would_recluster_workspaces": len(workspace_ids)}

        from donna.cortex.tasks import recluster_workspace

        total = 0
        for ws_id in workspace_ids:
            result = recluster_workspace.apply(args=[str(ws_id)]).get()
            total += result.get("reclustered_count", 0)
        return {"reclustered_count": total, "workspaces": len(workspace_ids)}

    # ── reap orphans ───────────────────────────────────────────────

    def _reap_orphans(self, dry_run: bool) -> dict:
        if dry_run:
            return {"note": "dry-run: reaper does not preview"}

        from donna.cortex.tasks import reap_orphan_bodies

        return reap_orphan_bodies.apply().get()
