"""P0 correctness fix tests — pure logic where possible (no Django DB)
plus a few that need the real DB.

DB-bound tests are marked at the class level; pure tests cover the
linter, clustering cosine floor, and doc_classifier — all of which
exercise no ORM and run without docker.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from donna.cortex.authority import RejectCode
from donna.cortex.clustering import HDBSCANClusterer, Scope
from donna.cortex.doc_classifier import HeuristicDocClassifier
from donna.cortex.linter import FrontmatterLinter, LinterError


def _stub_entity(**overrides):
    """Build an in-memory CortexEntity without hitting the DB.

    The linter never persists anything; we set workspace_id directly
    (bypassing FK validation) so this module can run outside Django's
    DB harness.
    """
    from donna.cortex.models import CortexEntity

    defaults = dict(
        id=uuid.uuid4(),
        type="email",
        author="donna",
        source="gmail://thread/abc",
        bronze_storage_key="bronze/x",
        content_hash="c" * 64,
        occurred_at=datetime.now(tz=timezone.utc),
        workspace_id=uuid.uuid4(),
        client_id=None,
        project_id=None,
        title="Test",
        body_byte_size=12,
        confidence="high",
        extensions={},
    )
    defaults.update(overrides)
    return CortexEntity(**defaults)


GOOD_BODY = "# T\n\nbody.\n\nSource: gmail://thread/abc"


class LinterScopeRelaxTests(unittest.TestCase):
    """_check_scope relaxed: (client_id=None, project_id=set) is allowed."""

    def setUp(self) -> None:
        self.linter = FrontmatterLinter()

    def test_workspace_internal_project_now_accepted(self) -> None:
        # Before relax: this raised INVALID_SCOPE. After relax: pass.
        entity = _stub_entity(client_id=None, project_id=uuid.uuid4())
        # Should not raise.
        self.linter.check(entity, body_md=GOOD_BODY)

    def test_workspace_root_still_accepted(self) -> None:
        entity = _stub_entity(client_id=None, project_id=None)
        self.linter.check(entity, body_md=GOOD_BODY)

    def test_client_project_still_accepted(self) -> None:
        entity = _stub_entity(client_id=uuid.uuid4(), project_id=uuid.uuid4())
        self.linter.check(entity, body_md=GOOD_BODY)


class LinterKnownEdgesTests(unittest.TestCase):
    """_check_known_edges: extensions must not carry edge field names."""

    def setUp(self) -> None:
        self.linter = FrontmatterLinter()

    def test_extension_with_edge_name_rejected(self) -> None:
        # ``sources`` is a real edge field name; placing it inside
        # extensions = adapter put data in the wrong slot.
        entity = _stub_entity(extensions={"sources": ["abc"]})
        with self.assertRaises(LinterError) as cm:
            self.linter.check(entity, body_md=GOOD_BODY)
        self.assertEqual(cm.exception.code, RejectCode.UNKNOWN_EDGE_TYPE)

    def test_legitimate_extensions_pass(self) -> None:
        entity = _stub_entity(
            type="doc",
            extensions={"doc_type": "spec"},
        )
        self.linter.check(entity, body_md=GOOD_BODY)


class ClusteringCosineFloorTests(unittest.TestCase):
    """#14 cosine floor — returns (None, None) below threshold."""

    def setUp(self) -> None:
        # Stub the centroid lookup so we don't need Postgres.
        class _StubClusterer(HDBSCANClusterer):
            def __init__(self, centroids, **kw):
                super().__init__(**kw)
                self._stub = centroids

            def _compute_centroids(self, scope):
                return self._stub

        self.Stub = _StubClusterer

    def test_below_floor_returns_none(self) -> None:
        # Centroid points along +X; query points along +Y → cosine ≈ 0.
        centroid = [1.0] + [0.0] * 383
        clusterer = self.Stub(
            centroids={uuid.uuid4(): (centroid, "TopicX")},
            min_similarity=0.55,
        )
        query = [0.0, 1.0] + [0.0] * 382
        cid, name = clusterer.assign(
            query, Scope(workspace_id=uuid.uuid4())
        )
        self.assertIsNone(cid)
        self.assertIsNone(name)

    def test_above_floor_assigns(self) -> None:
        centroid = [1.0] + [0.0] * 383
        cluster_id = uuid.uuid4()
        clusterer = self.Stub(
            centroids={cluster_id: (centroid, "TopicX")},
            min_similarity=0.55,
        )
        # Same direction as centroid → cosine 1.0.
        cid, name = clusterer.assign(
            [1.0] + [0.0] * 383, Scope(workspace_id=uuid.uuid4())
        )
        self.assertEqual(cid, cluster_id)
        self.assertEqual(name, "TopicX")


class DocClassifierTierATests(unittest.TestCase):
    """HeuristicDocClassifier — MIME / filename / body anchors."""

    def setUp(self) -> None:
        self.clf = HeuristicDocClassifier()

    def test_mime_pptx_maps_to_presentation(self) -> None:
        out = self.clf.classify(
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        self.assertEqual(out.doc_type, "presentation")
        self.assertEqual(out.basis, "mime")
        self.assertGreaterEqual(out.confidence, 0.9)

    def test_filename_nda_maps_to_contract(self) -> None:
        out = self.clf.classify(filename="Acme-NDA-2026.pdf")
        self.assertEqual(out.doc_type, "contract")
        self.assertEqual(out.basis, "filename")

    def test_body_anchor_whereas_witness_contract(self) -> None:
        body = "WHEREAS the parties agree…\n…\nIN WITNESS WHEREOF the parties hereto…"
        out = self.clf.classify(body_md=body)
        self.assertEqual(out.doc_type, "contract")
        self.assertEqual(out.basis, "anchor")

    def test_nothing_matches_returns_none(self) -> None:
        out = self.clf.classify(filename="notes.txt", body_md="hello world")
        self.assertIsNone(out.doc_type)
