"""Canonical adapter model tests — Phase 2 (2026-06-15).

Pure-Python — no DB. Exercises ``CanonicalEntity`` validation +
``BaseEntityAdapter.to_canonical()`` on the three live connectors.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from donna.core.integrations.canonical import CanonicalEntity
from donna.integrations.connectors.fathom.adapter import FathomMeetingAdapter
from donna.integrations.connectors.google.drive.adapter import DriveFileAdapter


class CanonicalEntityTests(unittest.TestCase):
    def test_valid_email_constructs(self) -> None:
        e = CanonicalEntity(
            entity_type="email",
            external_id="x1",
            title="Hi",
            occurred_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            extensions={"thread_id": "t1"},
        )
        self.assertEqual(e.entity_type, "email")
        self.assertEqual(e.extensions["thread_id"], "t1")

    def test_doc_missing_doc_type_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CanonicalEntity(
                entity_type="doc",
                external_id="x1",
                title="Spec",
                occurred_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
                extensions={},  # missing required doc_type
            )

    def test_unknown_entity_type_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CanonicalEntity(
                entity_type="banana",  # not in EntityType literal
                external_id="x1",
                title="x",
                occurred_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
                extensions={},
            )

    def test_as_payload_round_trip(self) -> None:
        e = CanonicalEntity(
            entity_type="meeting",
            external_id="m1",
            title="Standup",
            occurred_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            extensions={"attendees": [{"name": "Ada", "email": "a@x.com"}]},
        )
        payload = e.as_payload()
        self.assertEqual(payload["entity_type"], "meeting")
        # JSON-safe — re-validates round-trip.
        e2 = CanonicalEntity(**payload)
        self.assertEqual(e2.title, "Standup")


class FathomCanonicalTests(unittest.TestCase):
    def test_to_canonical_emits_meeting(self) -> None:
        raw = {
            "meeting": {
                "id": "rec-42",
                "title": "Sales sync",
                "recorded_at": "2026-06-10T14:00:00Z",
                "duration_seconds": 1800,
                "participants": [{"name": "Ada", "email": "ada@acme.com"}],
                "host": {"email": "ada@acme.com"},
            },
            "transcript": {"segments": []},
        }
        adapter = FathomMeetingAdapter(raw)
        canonical = adapter.to_canonical()
        self.assertEqual(canonical.entity_type, "meeting")
        self.assertEqual(canonical.external_id, "rec-42")
        self.assertEqual(canonical.title, "Sales sync")
        self.assertEqual(canonical.extensions["duration_min"], 30)
        self.assertEqual(len(canonical.extensions["attendees"]), 1)


class DriveCanonicalTests(unittest.TestCase):
    def test_to_canonical_emits_doc_with_default_type(self) -> None:
        raw = {
            "file": {
                "id": "f1",
                "name": "Acme NDA.pdf",
                "mimeType": "application/pdf",
                "modifiedTime": "2026-06-10T14:00:00Z",
                "owners": [{"emailAddress": "ada@acme.com"}],
                "webViewLink": "https://drive.google.com/x",
            },
        }
        adapter = DriveFileAdapter(raw)
        canonical = adapter.to_canonical()
        self.assertEqual(canonical.entity_type, "doc")
        # Adapter defaults doc_type to "other"; cortex tier-A classifier
        # upgrades when filename matches (NDA → contract).
        self.assertEqual(canonical.extensions["doc_type"], "other")
        self.assertEqual(canonical.extensions["filename"], "Acme NDA.pdf")
        self.assertEqual(canonical.extensions["author_email"], "ada@acme.com")
