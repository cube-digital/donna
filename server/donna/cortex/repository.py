"""
CortexEntityRepository — atomic data access for the Cortex layer.

Hides Django ORM from services. Maintains the **three** bidirectional
edge invariants per spec §4 inside one Postgres transaction:

- ``sources`` ↔ ``applied_in``
- ``supersedes`` ↔ ``superseded_by``
- ``contradicts`` ↔ ``contradicts`` (symmetric)

Also exposes:

- ``find_by_id`` — direct lookup
- ``find_referencing`` — derived entity-axis view (rows whose
  ``entity_refs`` contains the target id)
- ``find_in_scope`` — workspace + client + project tri-key lookup
"""
from __future__ import annotations

from uuid import UUID

from django.core.files.base import ContentFile
from django.db import transaction

from donna.cortex.models import CortexEntity


class CortexEntityRepository:
    """Atomic data access; preserves the three bidirectional edge invariants."""

    def save_with_reverse_edges(
        self,
        entity: CortexEntity,
        body_bytes: bytes | None = None,
    ) -> CortexEntity:
        """Persist ``entity`` and apply every reverse-edge update in one txn.

        Reverse-edge contract per spec §4:

        | Forward field    | Reverse field      | Cardinality |
        |------------------|--------------------|--------------|
        | ``sources[]``    | ``applied_in[]``   | append       |
        | ``supersedes[]`` | ``superseded_by``  | assign (1:1) |
        | ``contradicts[]``| ``contradicts[]``  | symmetric    |

        Args:
            entity: Unsaved CortexEntity in memory.
            body_bytes: Rendered markdown body to write to the
                FileField. ``None`` means the body is already attached
                (e.g. spawned curated row written by the resolver).
        """
        sources = self._uuids(entity.sources)
        supersedes = self._uuids(entity.supersedes)
        contradicts = self._uuids(entity.contradicts)

        with transaction.atomic():
            entity.save()
            if body_bytes is not None:
                entity.body.save(
                    name=f"{entity.id}.md",
                    content=ContentFile(body_bytes),
                    save=True,
                )
            for target_id in sources:
                self._append_applied_in(target_id, entity.id)
            for target_id in supersedes:
                self._assign_superseded_by(target_id, entity.id)
            for target_id in contradicts:
                self._append_contradicts(target_id, entity.id)
        return entity

    # ── reverse edge writers ────────────────────────────────────────

    def _append_applied_in(self, target_id: UUID, source_id: UUID) -> None:
        try:
            target = CortexEntity.objects.select_for_update().get(id=target_id)
        except CortexEntity.DoesNotExist:
            return
        applied_in = list(target.applied_in or [])
        if str(source_id) not in [str(x) for x in applied_in]:
            applied_in.append(str(source_id))
        target.applied_in = applied_in
        target.save(update_fields=["applied_in", "updated_at"])

    def _assign_superseded_by(self, target_id: UUID, source_id: UUID) -> None:
        try:
            target = CortexEntity.objects.select_for_update().get(id=target_id)
        except CortexEntity.DoesNotExist:
            return
        if target.superseded_by != source_id:
            target.superseded_by = source_id
            target.save(update_fields=["superseded_by", "updated_at"])

    def _append_contradicts(self, target_id: UUID, source_id: UUID) -> None:
        try:
            target = CortexEntity.objects.select_for_update().get(id=target_id)
        except CortexEntity.DoesNotExist:
            return
        contradicts = list(target.contradicts or [])
        if str(source_id) not in [str(x) for x in contradicts]:
            contradicts.append(str(source_id))
        target.contradicts = contradicts
        target.save(update_fields=["contradicts", "updated_at"])

    # ── Queries ─────────────────────────────────────────────────────

    def find_by_id(self, id: UUID) -> CortexEntity | None:
        return CortexEntity.objects.filter(id=id).first()

    def find_referencing(
        self, target_id: UUID, workspace_id: UUID
    ) -> list[CortexEntity]:
        """Derived entity-axis view: rows that mention ``target_id``."""
        return list(
            CortexEntity.objects.filter(
                workspace_id=workspace_id,
                entity_refs__contains=[str(target_id)],
            )
        )

    def find_in_scope(
        self,
        workspace_id: UUID,
        client_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[CortexEntity]:
        """Tri-key boundary lookup (spec §6)."""
        qs = CortexEntity.objects.filter(workspace_id=workspace_id)
        qs = qs.filter(client_id=client_id) if client_id else qs.filter(client_id__isnull=True)
        if project_id is not None:
            qs = qs.filter(project_id=project_id)
        elif client_id is None:
            qs = qs.filter(project_id__isnull=True)
        return list(qs)

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _uuids(values) -> list[UUID]:
        if not values:
            return []
        out: list[UUID] = []
        for v in values:
            try:
                out.append(v if isinstance(v, UUID) else UUID(str(v)))
            except (ValueError, TypeError):
                continue
        return out
