"""CortexEntityManager — atomic data access for ``CortexEntity``.

Moved 2026-06-14 from ``models.py`` to keep models.py models-only
(Django convention). ``CortexEntity.objects`` still points here.

Owns the bidirectional-edge invariants per spec §4 — every reverse
edge update lives inside a single Postgres transaction so partial
writes cannot leave the index inconsistent.

| Forward field    | Reverse field      | Cardinality |
|------------------|--------------------|--------------|
| ``sources[]``    | ``applied_in[]``   | append       |
| ``supersedes[]`` | ``superseded_by``  | assign (1:1) |
| ``contradicts[]``| ``contradicts[]``  | symmetric    |
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models, transaction


if TYPE_CHECKING:
    from .models import CortexEntity


logger = logging.getLogger(__name__)


class DanglingEdgeError(RuntimeError):
    """Reverse-edge writer pointed at a target row that doesn't exist.

    Raised only when ``settings.DEBUG`` is True so test suites + dev
    environments catch the bug loudly; production logs the warning and
    continues to keep the write transaction succeeding (the reverse-
    edge invariant degrades gracefully — a missing target just means
    one fewer edge to maintain).
    """


def _missing_target(method: str, target_id: UUID, source_id: UUID) -> None:
    """Centralized handler — log + raise-in-DEBUG. See DanglingEdgeError."""
    logger.warning(
        "cortex_reverse_edge_missing_target",
        extra={
            "method": method,
            "target_id": str(target_id),
            "source_id": str(source_id),
        },
    )
    if getattr(settings, "DEBUG", False):
        raise DanglingEdgeError(
            f"{method}: target row {target_id} not found (source={source_id})"
        )


class CortexEntityManager(models.Manager):
    """Custom manager — see module docstring."""

    def save_with_reverse_edges(
        self,
        entity: "CortexEntity",
        body_bytes: bytes | None = None,
    ) -> "CortexEntity":
        """Persist ``entity`` and apply every reverse-edge update in one txn."""
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
            target = self.select_for_update().get(id=target_id)
        except self.model.DoesNotExist:
            _missing_target("_append_applied_in", target_id, source_id)
            return
        applied_in = list(target.applied_in or [])
        if str(source_id) not in [str(x) for x in applied_in]:
            applied_in.append(str(source_id))
        target.applied_in = applied_in
        target.save(update_fields=["applied_in", "updated_at"])

    def _assign_superseded_by(self, target_id: UUID, source_id: UUID) -> None:
        try:
            target = self.select_for_update().get(id=target_id)
        except self.model.DoesNotExist:
            _missing_target("_assign_superseded_by", target_id, source_id)
            return
        if target.superseded_by != source_id:
            # Phase 1 side-effect (2026-06-12): superseded ancestor stops
            # participating in retrieval/clustering. Body untouched (R1
            # immutability for audit / chain replay).
            target.superseded_by = source_id
            target.doc_embedding = None
            target.cluster_id = None
            target.save(update_fields=[
                "superseded_by",
                "doc_embedding",
                "cluster_id",
                "updated_at",
            ])

    def _append_contradicts(self, target_id: UUID, source_id: UUID) -> None:
        try:
            target = self.select_for_update().get(id=target_id)
        except self.model.DoesNotExist:
            _missing_target("_append_contradicts", target_id, source_id)
            return
        contradicts = list(target.contradicts or [])
        if str(source_id) not in [str(x) for x in contradicts]:
            contradicts.append(str(source_id))
        target.contradicts = contradicts
        target.save(update_fields=["contradicts", "updated_at"])

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
