"""
End-to-end CortexPipeline smoke on a synthetic Fathom DeliveryPackage.

OCR/adapter are stubbed via overriding ``CortexPipeline._body_for`` so
the test runs without docker, real bronze blobs, or LLM calls.
Embeddings + GLiNER are off; deterministic ProviderMetadata extractor
surfaces candidate persons / orgs.

Aligned with Cortex Universal Silver Specification v1 (rev 3).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

from donna.cortex.models import CortexEntity
from donna.cortex.pipeline import CortexPipeline
from donna.integrations.models import DeliveryPackage
from donna.workspaces.models import Workspace


class CortexPipelineTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}"
        )
        self.storage_key = f"{self.workspace.id}/fathom/meetings/rec-1.json"
        if not default_storage.exists(self.storage_key):
            default_storage.save(self.storage_key, ContentFile(b"{}"))

        self.dp = DeliveryPackage.objects.create(
            workspace=self.workspace,
            provider="fathom",
            provider_item_id="rec-1",
            provider_item_type="meeting",
            title="Cortex Kickoff",
            occurred_at=datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc),
            metadata={
                "host": {"name": "Alice", "email": "alice@acme.com"},
                "attendees": [
                    {"name": "Alice", "email": "alice@acme.com", "role": "host"},
                    {"name": "Bob", "email": "bob@example.com"},
                ],
                "duration_min": 30,
            },
            storage_key=self.storage_key,
            canonical_type="meeting",
            canonical_payload={
                "entity_type": "meeting",
                "external_id": "rec-1",
                "title": "Cortex Kickoff",
                "occurred_at": "2026-06-03T14:00:00+00:00",
                "extensions": {
                    "attendees": [
                        {"name": "Alice", "email": "alice@acme.com", "role": "host"},
                        {"name": "Bob", "email": "bob@example.com", "role": None},
                    ],
                    "duration_min": 30,
                    "recording_url": None,
                },
            },
        )

    def _make_writer(self) -> CortexPipeline:
        writer = CortexPipeline()
        writer._body_for = lambda dp: (  # type: ignore[method-assign]
            "# Cortex Kickoff\n\nDiscussed P0–P7. Stripe integration next."
        )
        return writer

    def test_meeting_writes_cortex_entity(self) -> None:
        writer = self._make_writer()
        entity = writer.write(self.dp)

        self.assertEqual(entity.type, "meeting")
        self.assertEqual(entity.workspace_id, self.workspace.id)
        self.assertEqual(entity.title, "Cortex Kickoff")
        self.assertEqual(entity.author, "donna")
        self.assertEqual(entity.source, "fathom://meeting/rec-1")
        self.assertEqual(entity.bronze_storage_key, self.storage_key)
        self.assertEqual(entity.confidence, "high")
        self.assertIsNotNone(entity.last_synthesized)
        self.assertIn("meetings/2026/06", entity.extensions["parent_path"])
        self.assertTrue(any(
            a["email"] == "alice@acme.com" for a in entity.extensions["attendees"]
        ))
        self.assertEqual(entity.extensions["duration_min"], 30)
        # Body lives in SilverStorage (P0.14); FileField points at it.
        self.assertTrue(entity.body.name)
        self.assertGreater(entity.body_byte_size, 0)
        body_md = entity.load_body()
        self.assertTrue(body_md.startswith("---"))
        self.assertIn("Source: fathom://meeting/rec-1", body_md)
        # Storage path follows the canonical layout
        # cortex/<workspace>/<type>/<id>.md
        self.assertIn(f"cortex/{self.workspace.id}/meeting/", entity.body.name)

    def test_person_org_spawn_and_entity_refs(self) -> None:
        writer = self._make_writer()
        entity = writer.write(self.dp)

        entity_refs = entity.entity_refs
        # alice + bob → 2 persons; acme.com → 1 org (example.com filtered as common)
        self.assertTrue(len(entity_refs) >= 2)

        # Each referenced row should exist as either person or org.
        for ref_id in entity_refs:
            row = CortexEntity.objects.get(id=ref_id)
            self.assertIn(row.type, ("person", "org"))
            self.assertEqual(row.author, "donna")
            self.assertTrue(row.source.startswith("cortex://spawn/"))
            self.assertEqual(row.confidence, "medium")

    def test_idempotent_first_write(self) -> None:
        writer = self._make_writer()
        first = writer.write(self.dp)
        self.assertIsNotNone(first.id)

    def test_sampler_applied_per_type(self) -> None:
        """P0.14: embed_entity receives the per-type sampler.

        Spy on the embedder to assert ``embed_entity`` is called with
        the meeting TypeSpec's ``uniform_sampler``.
        """
        from donna.cortex.embeddings import uniform_sampler

        captured = {}

        class SpyEmbedder:
            def embed(self, text):  # noqa: D401
                return [0.0] * 384

            def embed_entity(self, title, body_md, sampler=None):
                captured["title"] = title
                captured["body_md_len"] = len(body_md)
                captured["sampler"] = sampler
                return [0.0] * 384

        class SpyClusterer:
            def assign(self, embedding, scope):
                return None, None

            def recluster(self, scope):  # pragma: no cover — not invoked
                return {}

        writer = CortexPipeline(
            embedder=SpyEmbedder(),
            clusterer=SpyClusterer(),
        )
        writer._body_for = lambda dp: (  # type: ignore[method-assign]
            "# Cortex Kickoff\n\nDiscussed P0–P7. Stripe integration next."
        )
        writer.write(self.dp)

        self.assertEqual(captured["title"], "Cortex Kickoff")
        self.assertIs(captured["sampler"], uniform_sampler)
