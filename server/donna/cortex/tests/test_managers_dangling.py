"""Reverse-edge writer dangling-target tests (DB-bound).

Verifies the 2026-06-14 fix: missing reverse-edge target now logs +
raises ``DanglingEdgeError`` when ``settings.DEBUG`` is True. Without
DEBUG the writer still logs but returns gracefully so production
write transactions don't fail on a stale edge.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.test import TestCase, override_settings

from donna.cortex.managers import DanglingEdgeError
from donna.cortex.models import CortexEntity
from donna.workspaces.models import Workspace


def _make_entity(workspace, **overrides):
    defaults = dict(
        id=uuid.uuid4(),
        workspace=workspace,
        type="email",
        author="donna",
        source="gmail://thread/x",
        bronze_storage_key="",
        content_hash=uuid.uuid4().hex,
        occurred_at=datetime.now(tz=timezone.utc),
        title="t",
        body_byte_size=1,
        confidence="high",
        last_synthesized=datetime.now(tz=timezone.utc).date(),
        extensions={},
    )
    defaults.update(overrides)
    return CortexEntity(**defaults)


class DanglingSupersedesTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="W", slug=f"w-{uuid.uuid4().hex[:6]}"
        )

    @override_settings(DEBUG=True)
    def test_dangling_supersedes_raises_in_debug(self) -> None:
        bogus_target = uuid.uuid4()
        entity = _make_entity(self.workspace, supersedes=[str(bogus_target)])
        with self.assertRaises(DanglingEdgeError):
            CortexEntity.objects.save_with_reverse_edges(
                entity, body_bytes=b"# t\n\nSource: x"
            )

    @override_settings(DEBUG=False)
    def test_dangling_supersedes_silent_in_prod(self) -> None:
        bogus_target = uuid.uuid4()
        entity = _make_entity(self.workspace, supersedes=[str(bogus_target)])
        # Should NOT raise — production keeps the write transaction
        # succeeding even if the reverse-edge target is missing.
        saved = CortexEntity.objects.save_with_reverse_edges(
            entity, body_bytes=b"# t\n\nSource: x"
        )
        self.assertEqual(saved.id, entity.id)
