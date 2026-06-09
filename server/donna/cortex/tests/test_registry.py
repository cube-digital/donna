"""
TypeSpec registration + meeting Jinja render smoke.
Spec-aligned (rev 3).
"""
from __future__ import annotations

from datetime import datetime

from django.test import TestCase

from donna.cortex.registry import TemplateRegistry
from donna.cortex.schemas import MeetingExtensions
from donna.cortex.template_engine import TemplateEngine


class TypeSpecTests(TestCase):
    def test_all_twelve_types_registered(self) -> None:
        registry = TemplateRegistry()
        types = set(registry.types())
        expected = {
            "meeting", "email", "chat", "doc", "ticket",
            "clip", "note", "person", "org", "project",
            "concept", "decision",
        }
        self.assertEqual(types & expected, expected)

    def test_meeting_typespec(self) -> None:
        registry = TemplateRegistry()
        spec = registry.get("meeting")
        self.assertEqual(spec.template_path, "meeting.j2")
        self.assertEqual(spec.version, "meeting@v1")
        self.assertEqual(spec.extensions_model, MeetingExtensions)

    def test_meeting_renders(self) -> None:
        registry = TemplateRegistry()
        engine = TemplateEngine()
        spec = registry.get("meeting")
        data = {
            "parent_path": "clients/acme/projects/onboarding/meetings/2026/06",
            "slug": "2026-06-03-cortex-kickoff",
            "attendees": [
                {"name": "Alice", "email": "alice@acme.com", "role": "host"},
                {"name": "Bob", "email": "bob@example.com", "role": "attendee"},
            ],
            "duration_min": 30,
            "recording_url": "https://fathom.example/r/abc",
            "cluster_name": "Customer Onboarding",
        }
        body = engine.render(
            spec,
            data=data,
            body_input="# Cortex Kickoff\n\nDiscussed P0–P7.",
            title="Cortex Kickoff",
            occurred_at=datetime(2026, 6, 3, 14, 0, 0),
            source_uri="fathom://meeting/abc",
            bronze_storage_key="ws/fathom/meetings/abc.json",
        )
        self.assertIn("type: meeting", body)
        self.assertIn("alice@acme.com", body)
        self.assertIn("bob@example.com", body)
        self.assertIn("duration_min: 30", body)
        self.assertIn("Source: fathom://meeting/abc", body)
        self.assertIn("# Cortex Kickoff", body)
