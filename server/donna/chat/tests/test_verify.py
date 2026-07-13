"""Plan 13 §5.4 — adversarial verify tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from donna.chat.agents.tools.base import ToolContext
from donna.chat.agents.verify import _extract_json, verify_finding


def _ctx():
    return ToolContext(
        workspace=SimpleNamespace(id="ws"),
        user=SimpleNamespace(id="u"),
        channel=SimpleNamespace(id="ch"),
        agent_session=SimpleNamespace(id="ag"),
    )


class ExtractJSONTests(SimpleTestCase):
    def test_clean_json(self):
        self.assertEqual(_extract_json('{"refuted": false}'), {"refuted": False})

    def test_fenced_json(self):
        out = _extract_json('```json\n{"refuted": true}\n```')
        self.assertEqual(out, {"refuted": True})

    def test_embedded_json(self):
        out = _extract_json('reasoning... {"refuted": false, "reason": "ok"} done.')
        self.assertEqual(out["refuted"], False)

    def test_garbage_returns_none(self):
        self.assertIsNone(_extract_json("not even close"))


class VerifyFindingTests(SimpleTestCase):
    def _patch_vote(self, votes):
        """Patch _one_vote to return a queued list of votes round-robin."""
        from itertools import cycle
        it = cycle(votes)

        def fake(*_args, **_kwargs):
            return next(it)

        return patch("donna.chat.agents.verify._one_vote", side_effect=fake)

    def test_all_refute_returns_refuted(self):
        votes = [{"refuted": True, "reason": "no evidence"}] * 3
        with self._patch_vote(votes):
            verdict, out = verify_finding(claim="x", ctx=_ctx(), n=3)
        self.assertEqual(verdict, "refuted")
        self.assertEqual(len(out), 3)

    def test_all_stand_returns_stands(self):
        votes = [{"refuted": False, "reason": "found it"}] * 3
        with self._patch_vote(votes):
            verdict, _ = verify_finding(claim="x", ctx=_ctx(), n=3)
        self.assertEqual(verdict, "stands")

    def test_majority_refute_returns_refuted(self):
        votes = [
            {"refuted": True, "reason": "no"},
            {"refuted": True, "reason": "no"},
            {"refuted": False, "reason": "yes"},
        ]
        with self._patch_vote(votes):
            verdict, _ = verify_finding(claim="x", ctx=_ctx(), n=3)
        self.assertEqual(verdict, "refuted")

    def test_n_clamped_to_max_five(self):
        votes = [{"refuted": False, "reason": ""}]
        with self._patch_vote(votes):
            verdict, out = verify_finding(claim="x", ctx=_ctx(), n=99)
        self.assertEqual(len(out), 5)

    def test_n_clamped_to_min_one(self):
        votes = [{"refuted": False, "reason": ""}]
        with self._patch_vote(votes):
            verdict, out = verify_finding(claim="x", ctx=_ctx(), n=0)
        self.assertEqual(len(out), 1)

    def test_verifier_error_treated_as_refuted(self):
        """If the subagent itself crashes, the claim must NOT be allowed
        through silently. Safety > false positives in v1."""
        with patch(
            "donna.chat.agents.verify.run_subagent_sync",
            return_value={"error": "api down", "text": ""},
        ):
            verdict, votes = verify_finding(claim="x", ctx=_ctx(), n=1)
        self.assertEqual(verdict, "refuted")
        self.assertIn("api down", votes[0]["reason"])
