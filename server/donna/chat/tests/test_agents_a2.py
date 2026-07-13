"""A2 drafting layer tests.

Covers the four-tool lifecycle (create / read / update / finalize)
against real DB rows so partial-unique + select_for_update + integrity
constraints exercise. DrafterNode + CortexService are stubbed because
they call external models / write to cortex — orthogonal to the draft
plumbing being tested here.

Matrix (from 00j §A2 Tests row):
- partial-unique blocks second draft
- read returns body + version
- update bumps version under select_for_update
- version conflict surfaces re-read error
- finalize linter-reject loop
- finalize writes entity + flips status + pins finalized_entity_id
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import TestCase

from donna.chat.agents.nodes.drafter import DraftOutput
from donna.chat.agents.tools.base import ToolContext
from donna.chat.agents.tools.draft_tools import (
    CreateDraftArgs,
    CreateDraftTool,
    FinalizeDraftArgs,
    FinalizeDraftTool,
    ReadDraftArgs,
    ReadDraftTool,
    UpdateDraftSectionArgs,
    UpdateDraftSectionTool,
)
from donna.chat.models import AgentSession, Channel, Artifact
from donna.workspaces.models import Workspace


# ── stubs ──────────────────────────────────────────────────────────────


class _StubDrafter:
    """Deterministic drafter — captures args, returns scripted DraftOutput."""

    def __init__(self, markdown: str = "## Section\n\nRevised body.", summary: str = "added section"):
        self._md = markdown
        self._summary = summary
        self.calls: list[dict] = []

    def revise(self, *, current, instruction, context, title, target_doc_type):
        self.calls.append({
            "current": current, "instruction": instruction,
            "context": list(context), "title": title,
            "target_doc_type": target_doc_type,
        })
        return DraftOutput(markdown=self._md, summary=self._summary)


class _StubVerdict:
    def __init__(self, ok: bool, codes=None):
        self.ok = ok
        self.codes = list(codes or [])


class _StubCortexService:
    """Patch target for CortexService — captures create_entity / linter_check."""

    def __init__(self, verdict_ok: bool = True, verdict_codes=None, entity_id=None):
        self._verdict = _StubVerdict(verdict_ok, verdict_codes)
        self._entity_id = entity_id or uuid4()
        self.linter_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def linter_check(self, *, type, body_md, extensions, title="draft"):
        self.linter_calls.append({
            "type": type, "body_md": body_md,
            "extensions": extensions, "title": title,
        })
        return self._verdict

    def create_entity(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id=self._entity_id)


# ── fixture helpers ────────────────────────────────────────────────────


def _make_ws_and_channel(slug: str) -> tuple[Workspace, Channel, AgentSession]:
    ws = Workspace.objects.create(name="T", slug=slug)
    ch = Channel.objects.create(
        workspace=ws,
        kind=Channel.Kind.DIRECT,
        visibility=Channel.Visibility.PRIVATE,
    )
    session = AgentSession.objects.create(channel=ch, name="Donna")
    return ws, ch, session


def _ctx(ws: Workspace, ch: Channel, session: AgentSession) -> ToolContext:
    return ToolContext(workspace=ws, user=None, channel=ch, agent_session=session)


# ── CreateDraftTool ────────────────────────────────────────────────────


class CreateDraftTests(TestCase):
    def test_creates_drafting_document_at_v0(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-create-1")
        tool = CreateDraftTool()
        res = tool.run(CreateDraftArgs(title="Project Brief", target_doc_type="brief"), _ctx(ws, ch, sess))

        self.assertIsNone(res.error)
        self.assertEqual(res.payload["version"], 0)
        self.assertEqual(res.payload["status"], Artifact.Status.DRAFTING)
        self.assertEqual(res.payload["title"], "Project Brief")
        self.assertEqual(res.payload["target_doc_type"], "brief")
        self.assertEqual(Artifact.objects.filter(channel=ch).count(), 1)

    def test_second_draft_blocked_by_partial_unique(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-create-2")
        tool = CreateDraftTool()
        tool.run(CreateDraftArgs(title="First", target_doc_type="note"), _ctx(ws, ch, sess))

        res2 = tool.run(CreateDraftArgs(title="Second", target_doc_type="note"), _ctx(ws, ch, sess))

        self.assertIsNotNone(res2.error)
        self.assertIn("already active", res2.error)
        self.assertEqual(Artifact.objects.filter(channel=ch, status=Artifact.Status.DRAFTING).count(), 1)

    def test_finalized_draft_does_not_block_new(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-create-3")
        tool = CreateDraftTool()
        first = tool.run(CreateDraftArgs(title="First", target_doc_type="note"), _ctx(ws, ch, sess))
        Artifact.objects.filter(id=first.payload["artifact_id"]).update(
            status=Artifact.Status.FINALIZED, finalized_entity_id=uuid4(),
        )

        second = tool.run(CreateDraftArgs(title="Second", target_doc_type="note"), _ctx(ws, ch, sess))

        self.assertIsNone(second.error)
        self.assertEqual(Artifact.objects.filter(channel=ch).count(), 2)


# ── ReadDraftTool ──────────────────────────────────────────────────────


class ReadDraftTests(TestCase):
    def test_returns_body_and_version(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-read-1")
        draft = Artifact.objects.create(
            channel=ch, title="Spec", body="# Spec\n\nBody.",
            status=Artifact.Status.DRAFTING, version=3, target_doc_type="spec",
        )
        res = ReadDraftTool().run(ReadDraftArgs(), _ctx(ws, ch, sess))

        self.assertIsNone(res.error)
        self.assertEqual(res.payload["artifact_id"], str(draft.id))
        self.assertEqual(res.payload["version"], 3)
        self.assertEqual(res.payload["body"], "# Spec\n\nBody.")
        self.assertEqual(res.payload["target_doc_type"], "spec")

    def test_missing_draft_returns_friendly_error(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-read-2")
        res = ReadDraftTool().run(ReadDraftArgs(), _ctx(ws, ch, sess))
        self.assertIsNotNone(res.error)
        self.assertIn("No active draft", res.error)


# ── UpdateDraftSectionTool ─────────────────────────────────────────────


class UpdateDraftSectionTests(TestCase):
    def test_bumps_version_and_replaces_body(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-upd-1")
        Artifact.objects.create(
            channel=ch, title="Brief", body="initial",
            status=Artifact.Status.DRAFTING, version=0, target_doc_type="brief",
        )
        drafter = _StubDrafter(markdown="# Brief\n\nRevised content here.", summary="added intro")
        tool = UpdateDraftSectionTool(drafter=drafter)

        res = tool.run(
            UpdateDraftSectionArgs(instruction="rewrite intro", expected_version=0),
            _ctx(ws, ch, sess),
        )

        self.assertIsNone(res.error)
        self.assertEqual(res.payload["version"], 1)
        self.assertEqual(res.payload["summary"], "added intro")
        d = Artifact.objects.get(channel=ch, status=Artifact.Status.DRAFTING)
        self.assertEqual(d.version, 1)
        self.assertEqual(d.body, "# Brief\n\nRevised content here.")
        self.assertEqual(len(drafter.calls), 1)
        self.assertEqual(drafter.calls[0]["instruction"], "rewrite intro")

    def test_version_conflict_returns_error_no_change(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-upd-2")
        Artifact.objects.create(
            channel=ch, title="Brief", body="initial",
            status=Artifact.Status.DRAFTING, version=2, target_doc_type="brief",
        )
        drafter = _StubDrafter()
        tool = UpdateDraftSectionTool(drafter=drafter)

        res = tool.run(
            UpdateDraftSectionArgs(instruction="x", expected_version=1),
            _ctx(ws, ch, sess),
        )

        self.assertIsNotNone(res.error)
        self.assertIn("v2", res.error)
        d = Artifact.objects.get(channel=ch)
        self.assertEqual(d.version, 2)
        self.assertEqual(d.body, "initial")
        self.assertEqual(len(drafter.calls), 0, "drafter ran despite version conflict")

    def test_no_draft_returns_friendly_error(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-upd-3")
        res = UpdateDraftSectionTool(drafter=_StubDrafter()).run(
            UpdateDraftSectionArgs(instruction="x", expected_version=0),
            _ctx(ws, ch, sess),
        )
        self.assertIsNotNone(res.error)
        self.assertIn("No active draft", res.error)


# ── FinalizeDraftTool ──────────────────────────────────────────────────


class FinalizeDraftTests(TestCase):
    def _patch_cortex(self, stub: _StubCortexService):
        from unittest.mock import patch
        return patch("donna.chat.agents.tools.draft_tools.CortexService", return_value=stub)

    def test_linter_pass_creates_entity_and_finalizes(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-fin-1")
        draft = Artifact.objects.create(
            channel=ch, title="Brief", body="# Brief\n\nBody.",
            status=Artifact.Status.DRAFTING, version=3, target_doc_type="brief",
        )
        entity_id = uuid4()
        stub = _StubCortexService(verdict_ok=True, entity_id=entity_id)

        with self._patch_cortex(stub):
            res = FinalizeDraftTool().run(FinalizeDraftArgs(title="Final Brief"), _ctx(ws, ch, sess))

        self.assertIsNone(res.error)
        self.assertEqual(res.payload["entity_id"], str(entity_id))
        self.assertEqual(res.payload["artifact_id"], str(draft.id))

        draft.refresh_from_db()
        self.assertEqual(draft.status, Artifact.Status.FINALIZED)
        self.assertEqual(draft.finalized_entity_id, entity_id)

        self.assertEqual(len(stub.linter_calls), 1)
        self.assertEqual(stub.linter_calls[0]["extensions"], {"doc_type": "brief"})
        self.assertIn("Source: donna://channel/", stub.linter_calls[0]["body_md"])

        self.assertEqual(len(stub.create_calls), 1)
        self.assertEqual(stub.create_calls[0]["type"], "doc")
        self.assertEqual(stub.create_calls[0]["author"], "agent")
        self.assertEqual(stub.create_calls[0]["title"], "Final Brief")

    def test_linter_reject_does_not_create_entity_or_finalize(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-fin-2")
        draft = Artifact.objects.create(
            channel=ch, title="Brief", body="bad body",
            status=Artifact.Status.DRAFTING, version=1, target_doc_type="brief",
        )
        stub = _StubCortexService(verdict_ok=False, verdict_codes=["MISSING_SOURCE", "SCOPE_BOUNDARY"])

        with self._patch_cortex(stub):
            res = FinalizeDraftTool().run(FinalizeDraftArgs(), _ctx(ws, ch, sess))

        self.assertIsNone(res.error)
        self.assertEqual(res.payload["rejected_codes"], ["MISSING_SOURCE", "SCOPE_BOUNDARY"])
        self.assertEqual(res.payload["artifact_id"], str(draft.id))

        draft.refresh_from_db()
        self.assertEqual(draft.status, Artifact.Status.DRAFTING, "draft finalized despite lint reject")
        self.assertIsNone(draft.finalized_entity_id)
        self.assertEqual(len(stub.create_calls), 0, "entity created despite lint reject")

    def test_empty_body_returns_friendly_error(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-fin-3")
        Artifact.objects.create(
            channel=ch, title="Brief", body="   ",
            status=Artifact.Status.DRAFTING, version=0, target_doc_type="brief",
        )
        stub = _StubCortexService(verdict_ok=True)
        with self._patch_cortex(stub):
            res = FinalizeDraftTool().run(FinalizeDraftArgs(), _ctx(ws, ch, sess))

        self.assertIsNotNone(res.error)
        self.assertIn("empty", res.error.lower())
        self.assertEqual(len(stub.linter_calls), 0)

    def test_missing_draft_returns_friendly_error(self) -> None:
        ws, ch, sess = _make_ws_and_channel("a2-fin-4")
        with self._patch_cortex(_StubCortexService()):
            res = FinalizeDraftTool().run(FinalizeDraftArgs(), _ctx(ws, ch, sess))
        self.assertIsNotNone(res.error)
        self.assertIn("No active draft", res.error)
