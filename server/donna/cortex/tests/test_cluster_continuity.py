"""P3 cluster identity continuity tests — pure Python (no DB).

Exercises ``_match_centroids`` directly with synthetic centroids.
End-to-end DB test deferred until embeddings + HDBSCAN run in CI;
the matching algorithm is the load-bearing piece + worth unit-testing.
"""
from __future__ import annotations

import unittest
import uuid

from donna.cortex.tasks import _match_centroids


def _vec(direction: int, dim: int = 384) -> list[float]:
    """One-hot-ish unit vector along axis ``direction``."""
    out = [0.0] * dim
    out[direction] = 1.0
    return out


class MatchCentroidsTests(unittest.TestCase):
    def test_pure_relabel_preserves_uuids(self) -> None:
        # Old + new centroids identical (same docs, shuffled order).
        # Every new cluster should match an old one → UUIDs preserved.
        old_a, old_b = uuid.uuid4(), uuid.uuid4()
        new_x, new_y = uuid.uuid4(), uuid.uuid4()

        old = {old_a: (_vec(0), "Topic A"), old_b: (_vec(1), "Topic B")}
        new = {new_x: _vec(1), new_y: _vec(0)}  # shuffled vs old

        remap_id, remap_name = _match_centroids(new, old)
        # Greedy match: new_x (axis 1) → old_b, new_y (axis 0) → old_a.
        self.assertEqual(remap_id[new_x], old_b)
        self.assertEqual(remap_id[new_y], old_a)
        self.assertEqual(remap_name[old_a], "Topic A")
        self.assertEqual(remap_name[old_b], "Topic B")

    def test_new_topic_no_match(self) -> None:
        # Old centroid along axis 0; new centroid along axis 5 → cosine 0.
        # Below the 0.80 threshold → no remap, new UUID stays.
        old_a = uuid.uuid4()
        new_x = uuid.uuid4()
        remap_id, _ = _match_centroids({new_x: _vec(5)}, {old_a: (_vec(0), "T")})
        self.assertEqual(remap_id, {})

    def test_greedy_assignment_skips_collisions(self) -> None:
        # Two new clusters both close to ONE old centroid.
        # Greedy: highest score wins, the other gets nothing.
        old_a = uuid.uuid4()
        new_x, new_y = uuid.uuid4(), uuid.uuid4()
        nearly = [0.95] + [0.0] * 383
        same_as_old = _vec(0)
        old = {old_a: (same_as_old, "A")}
        new = {new_x: same_as_old, new_y: nearly}

        remap_id, _ = _match_centroids(new, old)
        # Either new_x or new_y wins; the OTHER is unmapped.
        self.assertEqual(len(remap_id), 1)
        self.assertIn(list(remap_id.values())[0], {old_a})

    def test_threshold_excludes_borderline(self) -> None:
        # Cosine ~0.6 between old (axis 0) and new ([0.6, 0.8]).
        # 0.6 < 0.80 threshold → no match.
        old_a = uuid.uuid4()
        new_x = uuid.uuid4()
        borderline = [0.6, 0.8] + [0.0] * 382
        remap_id, _ = _match_centroids(
            {new_x: borderline}, {old_a: (_vec(0), "A")}
        )
        self.assertEqual(remap_id, {})

    def test_empty_inputs(self) -> None:
        self.assertEqual(_match_centroids({}, {}), ({}, {}))
