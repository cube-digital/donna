"""
CortexEntity.objects.save_with_reverse_edges — atomic reverse-edge
write tests for the three bidirectional pairs (sources↔applied_in,
supersedes↔superseded_by, contradicts↔contradicts).

Aligned with Cortex Universal Silver Specification v1 (rev 3) §4 and
P0.14 (body to SilverStorage via FileField).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from django.test import TestCase

from donna.cortex.models import CortexEntity
from donna.workspaces.models import Workspace


class CortexEntityManagerSaveTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}"
        )

    def _make_entity_and_body(
        self,
        *,
        type_: str = "meeting",
        body: str = "# meeting\n\nSource: ws/fathom/x.json",
        sources: list[str] | None = None,
        supersedes: list[str] | None = None,
        entity_refs: list[str] | None = None,
    ) -> tuple[CortexEntity, bytes]:
        body_bytes = body.encode("utf-8")
        entity = CortexEntity(
            workspace=self.workspace,
            type=type_,
            author="donna",
            source=f"fathom://meeting/{uuid.uuid4()}",
            bronze_storage_key="ws/fathom/x.json",
            occurred_at=datetime.now(tz=timezone.utc),
            title="Test entity",
            body_byte_size=len(body_bytes),
            content_hash=hashlib.sha256(body_bytes).hexdigest(),
            entity_refs=entity_refs or [],
            sources=sources or [],
            supersedes=supersedes or [],
            extensions={"slug": "test-slug", "parent_path": "_inbox"},
        )
        return entity, body_bytes

    def test_save_creates_row(self) -> None:
        entity, body_bytes = self._make_entity_and_body()
        CortexEntity.objects.save_with_reverse_edges(entity, body_bytes=body_bytes)
        self.assertEqual(CortexEntity.objects.count(), 1)
        entity.refresh_from_db()
        self.assertTrue(entity.body.name)
        self.assertGreater(entity.body_byte_size, 0)
        self.assertIn("Source:", entity.load_body())

    def test_sources_updates_applied_in(self) -> None:
        target, target_body = self._make_entity_and_body(
            type_="person",
            body="# Alice\n\nSpawned by: <none>",
        )
        CortexEntity.objects.save_with_reverse_edges(target, body_bytes=target_body)

        referring, ref_body = self._make_entity_and_body(
            sources=[str(target.id)]
        )
        CortexEntity.objects.save_with_reverse_edges(referring, body_bytes=ref_body)

        target.refresh_from_db()
        self.assertIn(str(referring.id), target.applied_in)

    def test_supersedes_assigns_superseded_by(self) -> None:
        original, orig_body = self._make_entity_and_body(
            type_="doc",
            body="# v1 plan\n\nSource: ws/x.md",
        )
        original.extensions = dict(original.extensions, doc_type="plan")
        CortexEntity.objects.save_with_reverse_edges(original, body_bytes=orig_body)

        revised, rev_body = self._make_entity_and_body(
            type_="doc",
            body="# v2 plan\n\nSource: ws/x2.md",
            supersedes=[str(original.id)],
        )
        revised.extensions = dict(revised.extensions, doc_type="plan")
        CortexEntity.objects.save_with_reverse_edges(revised, body_bytes=rev_body)

        original.refresh_from_db()
        self.assertEqual(original.superseded_by, revised.id)
