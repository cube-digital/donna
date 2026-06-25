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
            "--render",
            action="store_true",
            help=(
                "Phase 5: write the hierarchical vault projection to "
                "<vault>/<ws>/<parent_path>/<slug>.md for every entity, "
                "then regenerate every folder's _index.md."
            ),
        )
        parser.add_argument(
            "--reclassify-orgs",
            action="store_true",
            help=(
                "Run the org-relationship classifier ladder (Tier A rules + "
                "Tier B Haiku) over every org in scope. Re-derives "
                "parent_path so the next render re-files accordingly."
            ),
        )
        parser.add_argument(
            "--no-llm",
            action="store_true",
            help="With --reclassify-orgs: skip Tier B (LLM) — rules only.",
        )
        parser.add_argument(
            "--correct-orgs",
            metavar="CSV_PATH",
            help=(
                "Bulk manual override of org relationships from a CSV. "
                "Columns: slug,relationship,roles,client_of,lock. "
                "Rows where lock=true freeze the row against future "
                "classifier runs. roles is `|`-separated. "
                "client_of is `|`-separated slugs."
            ),
        )
        parser.add_argument(
            "--rebuild",
            action="store_true",
            help=(
                "FULL rebuild from vault files. Reconstructs CortexEntity "
                "rows from frontmatter; body content from .md body. Edges + "
                "embeddings recovered via subsequent --reindex-embeddings "
                "+ --rebuild-clusters."
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
                "render",
                "rebuild",
                "reclassify_orgs",
                "correct_orgs",
            )
        ):
            raise CommandError(
                "Pick at least one of --reindex-embeddings / "
                "--rebuild-clusters / --reap-orphans / --render / "
                "--rebuild / --reclassify-orgs / --correct-orgs."
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

        if opts.get("render"):
            report["render"] = self._render_vault(
                workspace_ids,
                dry_run=opts.get("dry_run", False),
            )

        if opts.get("rebuild"):
            report["rebuild"] = self._rebuild_from_vault(
                workspace_ids,
                dry_run=opts.get("dry_run", False),
            )

        if opts.get("reclassify_orgs"):
            report["reclassify_orgs"] = self._reclassify_orgs(
                workspace_ids,
                use_llm=not opts.get("no_llm", False),
            )

        if opts.get("correct_orgs"):
            report["correct_orgs"] = self._correct_orgs(
                workspace_ids,
                csv_path=opts["correct_orgs"],
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

    # ── correct orgs (00m, multi-label CSV import) ─────────────────

    def _correct_orgs(
        self,
        workspace_ids: list[UUID],
        *,
        csv_path: str,
    ) -> dict:
        """Bulk manual override from CSV.

        CSV columns (header required):
          slug             — org slug (e.g. ``robonnement``)
          relationship     — primary; one of {self, client, partner,
                             vendor, peer, unknown}. Drives folder routing.
          roles            — pipe-separated full label set, e.g.
                             ``partner|client`` for an org that's both.
                             If empty, defaults to ``[relationship]``.
          client_of        — pipe-separated org SLUGS this org is a
                             client of (indirect relationship).
                             Example: ``ki,, ,weasweb`` → ki client of weasweb.
          lock             — ``true`` to set ``relationship_locked=True``
                             so future classifier runs skip the row.

        Lines starting with ``#`` and blank lines are skipped.
        Multiple workspaces: the CSV is applied to every workspace in
        scope where a matching slug exists (typically one workspace).
        """
        import csv

        from donna.cortex.folders import org as org_folder_resolver
        from donna.cortex.models import CortexEntity

        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                # Skip comment lines
                rows = [
                    line for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
            reader = csv.DictReader(rows)
            entries = list(reader)
        except FileNotFoundError:
            raise CommandError(f"CSV not found: {csv_path}")

        if not entries:
            return {"applied": 0, "skipped_no_match": 0, "errors": 0}

        applied = skipped = errors = 0
        details: list[str] = []

        for ws_id in workspace_ids:
            # Build slug → org lookup once per workspace
            slug_to_org: dict[str, CortexEntity] = {}
            for org in CortexEntity.objects.filter(workspace_id=ws_id, type="org"):
                slug = (org.extensions or {}).get("slug")
                if slug:
                    slug_to_org[slug] = org

            for entry in entries:
                slug = (entry.get("slug") or "").strip()
                if not slug:
                    continue
                org = slug_to_org.get(slug)
                if org is None:
                    skipped += 1
                    details.append(f"skip {slug}: not in workspace {ws_id}")
                    continue

                try:
                    rel = (entry.get("relationship") or "unknown").strip().lower() or "unknown"
                    roles_raw = (entry.get("roles") or "").strip()
                    roles = [
                        r.strip().lower() for r in roles_raw.split("|") if r.strip()
                    ] if roles_raw else [rel]
                    client_of_raw = (entry.get("client_of") or "").strip()
                    client_of_slugs = [
                        s.strip() for s in client_of_raw.split("|") if s.strip()
                    ]
                    # Resolve slugs → UUIDs (skip unknown slugs, log)
                    client_of_uuids: list[str] = []
                    for cs in client_of_slugs:
                        target = slug_to_org.get(cs)
                        if target is None:
                            details.append(
                                f"warn {slug}: client_of=`{cs}` not found in workspace"
                            )
                            continue
                        client_of_uuids.append(str(target.id))

                    lock = (entry.get("lock") or "").strip().lower() in ("true", "1", "yes", "y")

                    ext = dict(org.extensions or {})
                    ext["relationship"] = rel
                    ext["roles"] = roles
                    ext["client_of"] = client_of_uuids
                    ext["relationship_basis"] = "manual"
                    ext["relationship_confidence"] = 1.0
                    ext["relationship_locked"] = lock
                    ext["relationship_evidence"] = ["manual CSV override"]
                    # Recompute parent_path against new primary
                    ext["parent_path"] = org_folder_resolver(
                        type="org",
                        occurred_at=None,
                        extensions=ext,
                        client_slug=None,
                        project_slug=None,
                    )
                    org.extensions = ext
                    org.save(update_fields=["extensions", "updated_at"])
                    applied += 1
                    details.append(
                        f"ok   {slug}: relationship={rel} roles={roles} "
                        f"client_of={len(client_of_uuids)} lock={lock}"
                    )
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    details.append(f"err  {slug}: {type(exc).__name__}: {exc}")

        for line in details:
            self.stdout.write(f"    {line}")
        return {
            "applied": applied,
            "skipped_no_match": skipped,
            "errors": errors,
        }

    # ── reclassify orgs (00m) ──────────────────────────────────────

    def _reclassify_orgs(
        self,
        workspace_ids: list[UUID],
        *,
        use_llm: bool,
    ) -> dict:
        from donna.cortex.tasks import reclassify_orgs

        aggregate = {
            "tier_a_decided": 0,
            "tier_b_decided": 0,
            "unchanged":      0,
            "skipped_locked": 0,
        }
        for ws_id in workspace_ids:
            result = reclassify_orgs.apply(
                args=[str(ws_id)],
                kwargs={"use_llm": use_llm},
            ).get()
            for k in aggregate:
                aggregate[k] += result.get(k, 0)
        return aggregate

    # ── reap orphans ───────────────────────────────────────────────

    def _reap_orphans(self, dry_run: bool) -> dict:
        if dry_run:
            return {"note": "dry-run: reaper does not preview"}

        from donna.cortex.tasks import reap_orphan_bodies

        return reap_orphan_bodies.apply().get()

    # ── render vault (Phase 5) ─────────────────────────────────────

    def _render_vault(
        self,
        workspace_ids: list[UUID],
        *,
        dry_run: bool,
    ) -> dict:
        from donna.cortex.models import CortexEntity
        from donna.cortex.vault_renderer import VaultRenderer

        qs = CortexEntity.objects.filter(
            workspace_id__in=workspace_ids,
            superseded_by__isnull=True,
        )
        total = qs.count()
        if dry_run:
            return {"would_render": total}

        renderer = VaultRenderer()
        rendered = 0
        folders: set[tuple[str, str]] = set()  # (ws_id, parent_path)
        for entity in qs.iterator(chunk_size=200):
            try:
                path = renderer.render_entity(entity)
                if path is not None:
                    rendered += 1
                    folders.add(
                        (str(entity.workspace_id),
                         (entity.extensions or {}).get("parent_path", "")),
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "cortex_sync_vault_render_failed",
                    extra={"entity_id": str(entity.id)},
                )

        # Regenerate every touched folder's _index.md inline (bypass beat).
        for ws_id, folder in folders:
            try:
                renderer.render_index(ws_id, folder)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "cortex_sync_vault_index_failed",
                    extra={"workspace_id": ws_id, "folder": folder},
                )
        return {
            "rendered_entities": rendered,
            "rendered_indexes":  len(folders),
            "candidates":        total,
        }

    # ── rebuild from vault (Phase 5 — spec §14) ────────────────────

    def _rebuild_from_vault(
        self,
        workspace_ids: list[UUID],
        *,
        dry_run: bool,
    ) -> dict:
        """Walk vault → reconstruct CortexEntity rows from frontmatter.

        Recovers: id, type, title, occurred_at, slug, parent_path, all
        type-extension fields embedded in frontmatter, body.

        Does NOT recover: doc_embedding, cluster_id, sources, applied_in,
        supersedes, superseded_by, contradicts. Run --reindex-embeddings
        + --rebuild-clusters afterward to refresh derivable state.

        Edge data is currently not in vault frontmatter; templates would
        need extending to embed it. This is the documented v1 limitation
        — round-trip recovers display-grade rows, not full graph state.
        """
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from donna.cortex.models import CortexEntity
        from donna.cortex.vault_renderer import parse_frontmatter, vault_root_for

        created = updated = skipped = errors = 0
        for ws_id in workspace_ids:
            ws_root = vault_root_for(ws_id)
            try:
                paths = list(_iter_md_files(default_storage, ws_root))
            except FileNotFoundError:
                continue

            for path in paths:
                # Skip index + log files
                base = path.rsplit("/", 1)[-1]
                if base in ("_index.md", "_log.md"):
                    continue

                try:
                    with default_storage.open(path, mode="rb") as f:
                        raw = f.read()
                    fm, body_md = parse_frontmatter(raw)
                    entity_id = fm.get("id")
                    if not entity_id:
                        skipped += 1
                        continue

                    if dry_run:
                        if CortexEntity.objects.filter(id=entity_id).exists():
                            updated += 1
                        else:
                            created += 1
                        continue

                    existing = CortexEntity.objects.filter(id=entity_id).first()
                    if existing:
                        # Verify content_hash matches; warn on drift.
                        expected = fm.get("content_hash") or ""
                        if expected and expected != (existing.content_hash or ""):
                            logger.warning(
                                "cortex_sync_rebuild_hash_drift",
                                extra={
                                    "entity_id":      entity_id,
                                    "expected_hash":  expected,
                                    "current_hash":   existing.content_hash,
                                },
                            )
                        updated += 1
                    else:
                        # Reconstruct row from frontmatter.
                        from datetime import datetime, timezone as _tz

                        occurred_str = fm.get("occurred_at") or ""
                        try:
                            # Frontmatter format: "2026-05-27 12:21:30+00:00"
                            # — fromisoformat needs T separator in <3.11,
                            # accepts space in 3.11+. We're on 3.13.
                            occurred = datetime.fromisoformat(
                                occurred_str.replace("Z", "+00:00")
                            )
                            if occurred.tzinfo is None:
                                occurred = occurred.replace(tzinfo=_tz.utc)
                        except (ValueError, TypeError):
                            # Last-resort fallback — fail loud rather
                            # than silently shifting time, but accept
                            # NOW so the rebuild can keep going.
                            occurred = datetime.now(tz=_tz.utc)
                            logger.warning(
                                "cortex_sync_rebuild_occurred_at_fallback",
                                extra={"entity_id": entity_id, "raw": occurred_str},
                            )

                        try:
                            ext: dict = {
                                k: v
                                for k, v in fm.items()
                                if k in {
                                    "slug", "parent_path",
                                    "cluster_name", "template_version",
                                }
                            }
                            # Restore org-relationship truth (00m) —
                            # vault is the canonical store after a DB
                            # wipe. Skip when absent (non-org rows).
                            if fm.get("relationship"):
                                ext["relationship"] = fm["relationship"]
                            if fm.get("roles"):
                                ext["roles"] = [
                                    r.strip() for r in fm["roles"].split("|") if r.strip()
                                ]
                            if fm.get("client_of"):
                                ext["client_of"] = [
                                    s.strip() for s in fm["client_of"].split("|") if s.strip()
                                ]
                            if fm.get("relationship_locked", "").lower() in ("true", "1", "yes"):
                                ext["relationship_locked"] = True

                            CortexEntity.objects.create(
                                id=entity_id,
                                workspace_id=ws_id,
                                type=fm.get("type", "doc"),
                                title=fm.get("title", "(untitled)"),
                                occurred_at=occurred,
                                source=fm.get("source", ""),
                                author=fm.get("author", "donna"),
                                content_hash=fm.get("content_hash", ""),
                                extensions=ext,
                                body=ContentFile(
                                    raw,
                                    name=f"{entity_id}.md",
                                ),
                            )
                            created += 1
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "cortex_sync_rebuild_create_failed",
                                extra={"entity_id": entity_id, "path": path},
                            )
                            errors += 1
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "cortex_sync_rebuild_file_failed",
                        extra={"path": path},
                    )
                    errors += 1

        return {
            "created": created,
            "updated": updated,
            "skipped_missing_id": skipped,
            "errors":  errors,
            "dry_run": dry_run,
        }


def _iter_md_files(storage, root: str):
    """Recursive walk of ``storage`` rooted at ``root`` → yield .md paths."""
    try:
        dirs, files = storage.listdir(root)
    except FileNotFoundError:
        return
    for f in files:
        if f.endswith(".md"):
            yield f"{root}/{f}"
    for d in dirs:
        yield from _iter_md_files(storage, f"{root}/{d}")
