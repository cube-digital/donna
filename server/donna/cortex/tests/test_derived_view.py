"""
DerivedNamespaceView — entity-axis projection over CortexEntity rows
whose ``entity_refs[]`` contains the target id.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from django.test import TestCase

from donna.cortex.folders import DerivedNamespaceView
from donna.cortex.models import CortexEntity
from donna.workspaces.models import Workspace


class DerivedNamespaceViewTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}"
        )
        self.view = DerivedNamespaceView()

    def _save(
        self,
        *,
        type_: str = "meeting",
        body: str = "# meeting\n\nSource: ws/fathom/x.json",
        entity_refs: list[str] | None = None,
    ) -> CortexEntity:
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
            extensions={"slug": "test-slug", "parent_path": "_inbox"},
        )
        CortexEntity.objects.save_with_reverse_edges(entity, body_bytes=body_bytes)
        return entity

    def test_list_entity_namespace_returns_referencing_rows(self) -> None:
        target = self._save(type_="org", body="# Acme\n\nSpawned by: <none>")
        referrer = self._save(entity_refs=[str(target.id)])
        # An unrelated row that does not reference the target.
        self._save(body="# other\n\nSource: ws/y.json")

        hits = self.view.list_entity_namespace(target.id, self.workspace.id)
        self.assertEqual([h.id for h in hits], [referrer.id])
