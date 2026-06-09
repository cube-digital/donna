"""
Embedding sampler smoke tests (P0.14).

We don't load the BGE-small model in tests — just verify the samplers
produce sane inputs within the BGE 512-token (~1900 char) budget.
"""
from __future__ import annotations

from django.test import SimpleTestCase

from donna.cortex.embeddings import (
    MAX_EMBED_CHARS,
    fixed_window_sampler,
    head_heavy_sampler,
    head_tail_sampler,
    uniform_sampler,
)


_BIG_BODY = "alpha " * 2000  # ~12 000 chars


class SamplerTests(SimpleTestCase):
    def test_fixed_window_short_body_passthrough(self) -> None:
        out = fixed_window_sampler("title", "short body")
        self.assertIn("title", out)
        self.assertIn("short body", out)
        self.assertLessEqual(len(out), MAX_EMBED_CHARS)

    def test_fixed_window_long_body_within_budget(self) -> None:
        out = fixed_window_sampler("title", _BIG_BODY)
        self.assertLessEqual(len(out), MAX_EMBED_CHARS)
        self.assertIn("[...]", out)
        # Both intro AND tail of the source are represented.
        self.assertTrue(out.startswith("title\n\nalpha"))
        self.assertTrue(out.rstrip().endswith("alpha"))

    def test_head_heavy_emphasises_head(self) -> None:
        out = head_heavy_sampler("t", _BIG_BODY)
        # 70% head means the largest single block is at the start.
        head_chunk = out.split("[...]")[0]
        tail_chunk = out.split("[...]")[-1]
        self.assertGreater(len(head_chunk), len(tail_chunk))

    def test_head_tail_skips_middle(self) -> None:
        out = head_tail_sampler("t", _BIG_BODY)
        # Exactly one separator → only two blocks (head + tail).
        self.assertEqual(out.count("[...]"), 1)
        self.assertLessEqual(len(out), MAX_EMBED_CHARS)

    def test_uniform_produces_multiple_windows(self) -> None:
        out = uniform_sampler("t", _BIG_BODY, windows=4)
        # 4 windows → 3 separators
        self.assertEqual(out.count("[...]"), 3)
        self.assertLessEqual(len(out), MAX_EMBED_CHARS)

    def test_samplers_differ_for_same_input(self) -> None:
        h = head_heavy_sampler("t", _BIG_BODY)
        t = head_tail_sampler("t", _BIG_BODY)
        u = uniform_sampler("t", _BIG_BODY)
        f = fixed_window_sampler("t", _BIG_BODY)
        # All four produce distinct outputs for the same big body.
        self.assertEqual(len({h, t, u, f}), 4)
