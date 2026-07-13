"""A2 draft tools — Cowork-style collaborative drafting in a channel.

Four tools form a small lifecycle:

1. ``create_draft`` — open a new ``Artifact(status=DRAFTING)`` in the
   channel. Partial unique constraint enforces one active draft per
   channel; second call returns a friendly error.
2. ``read_draft`` — return the current draft (body + version) so the
   agent can re-read before proposing changes (and confirm
   ``expected_version`` to detect concurrent edits).
3. ``update_draft_section`` — apply an instruction via DrafterNode
   (Sonnet); version bumps under ``select_for_update``; mismatch on
   ``expected_version`` returns a re-read error.
4. ``finalize_draft`` — lint via ``CortexService.linter_check``;
   on pass, ``CortexService.create_entity`` persists the body as a
   ``doc`` cortex entity; draft row flips to FINALIZED and pins the
   new entity id. On lint reject, returns the codes so the agent can
   fix and retry.

The draft cycle is intentionally short and explicit: there is no
implicit "continue last draft" — the agent must call ``create_draft``
or ``read_draft`` first. This keeps the partial-unique semantics
unambiguous.

WS broadcast: every state change (create/update/finalize/abandon)
fires a ``chat.artifact.updated`` event onto the channel group so
the frontend can re-render the draft pane.
"""
from __future__ import annotations

import logging
from typing import ClassVar
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from pydantic import BaseModel, Field

from donna.chat.agents.nodes.drafter import DrafterNode
from donna.chat.agents.tools.base import DonnaTool, ToolContext, ToolResult
from donna.chat.models import Artifact
from donna.chat.services import channel_group
from donna.cortex.services import CortexService


logger = logging.getLogger(__name__)


# ── helpers ────────────────────────────────────────────────────────────


def _broadcast_doc_updated(channel_id, draft: Artifact, action: str) -> None:
    """Push a ``chat.artifact.updated`` event onto the channel group."""
    layer = get_channel_layer()
    if layer is None:
        logger.warning("channel_layer_missing_for_doc_broadcast")
        return
    payload = {
        "type": "chat.artifact.updated",
        "payload": {
            "channel_id":            str(channel_id),
            "artifact":              {
                "id":                    str(draft.id),
                "status":                draft.status,
                "version":               draft.version,
                "title":                 draft.title,
                "target_doc_type":       draft.target_doc_type or "",
                "finalized_entity_id":   (
                    str(draft.finalized_entity_id) if draft.finalized_entity_id else None
                ),
            },
            "action":                action,
        },
    }
    try:
        async_to_sync(layer.group_send)(channel_group(channel_id), payload)
    except Exception:  # noqa: BLE001
        logger.exception(
            "chat_artifact_broadcast_failed",
            extra={"channel_id": str(channel_id), "artifact_id": str(draft.id)},
        )


# ── CreateDraftTool ────────────────────────────────────────────────────


class CreateDraftArgs(BaseModel):
    title: str = Field(description="Working title for the draft (can change later).")
    target_doc_type: str = Field(
        default="other",
        description=(
            "DocType vocab token (spec, contract, brief, runbook, note, "
            "other ...). Drives drafter tone + linter doc_type. Use "
            "'other' if unsure."
        ),
    )


class CreateDraftTool(DonnaTool):
    name: ClassVar[str] = "create_draft"
    description: ClassVar[str] = (
        "Open a new collaborative draft in this channel. Use when the "
        "user asks you to write, draft, propose, or compose a document. "
        "Only one active draft per channel — if one already exists, "
        "call read_draft first."
    )
    args_model: ClassVar[type[BaseModel]] = CreateDraftArgs
    taint_safe: ClassVar[bool] = True
    timeout_s: ClassVar[int] = 15

    def run(self, args: CreateDraftArgs, ctx: ToolContext) -> ToolResult:
        try:
            with transaction.atomic():
                draft = Artifact.objects.create(
                    channel=ctx.channel,
                    title=args.title,
                    body="",
                    status=Artifact.Status.DRAFTING,
                    version=0,
                    target_doc_type=args.target_doc_type or "other",
                    created_by=ctx.user,
                    modified_by=ctx.user,
                )
        except IntegrityError:
            existing = (
                Artifact.objects
                .filter(channel=ctx.channel, status=Artifact.Status.DRAFTING)
                .first()
            )
            existing_id = str(existing.id) if existing else "unknown"
            return ToolResult.fail(
                f"A draft is already active in this channel "
                f"(artifact_id={existing_id}). Call read_draft first, "
                f"then update_draft_section to revise it."
            )

        _broadcast_doc_updated(ctx.channel.id, draft, action="created")
        return ToolResult(payload={
            "artifact_id":     str(draft.id),
            "version":         draft.version,
            "status":          draft.status,
            "title":           draft.title,
            "target_doc_type": draft.target_doc_type,
        })


# ── ReadDraftTool ──────────────────────────────────────────────────────


class ReadDraftArgs(BaseModel):
    pass


class ReadDraftTool(DonnaTool):
    name: ClassVar[str] = "read_draft"
    description: ClassVar[str] = (
        "Read the current active draft for this channel — returns the "
        "full body, current version, title, and target_doc_type. Call "
        "before update_draft_section so you have a fresh expected_version."
    )
    args_model: ClassVar[type[BaseModel]] = ReadDraftArgs
    taint_safe: ClassVar[bool] = True
    timeout_s: ClassVar[int] = 10

    def run(self, args: ReadDraftArgs, ctx: ToolContext) -> ToolResult:
        draft = (
            Artifact.objects
            .filter(channel=ctx.channel, status=Artifact.Status.DRAFTING)
            .first()
        )
        if draft is None:
            return ToolResult.fail(
                "No active draft in this channel. Call create_draft first."
            )
        return ToolResult(payload={
            "artifact_id":     str(draft.id),
            "version":         draft.version,
            "title":           draft.title,
            "target_doc_type": draft.target_doc_type,
            "body":            draft.body,
        })


# ── UpdateDraftSectionTool ─────────────────────────────────────────────


class UpdateDraftSectionArgs(BaseModel):
    instruction: str = Field(
        description=(
            "What to do to the draft, in plain English. Examples: "
            "'add a section about late fees', 'tighten the opening', "
            "'replace the timeline with the one from snippet 2'."
        ),
    )
    expected_version: int = Field(
        description=(
            "The version returned by your most recent read_draft / "
            "create_draft / update_draft_section call. Mismatch returns "
            "a re-read error — do NOT guess; re-read first."
        ),
    )
    context_snippets: list[dict] = Field(
        default_factory=list,
        description=(
            "Optional retrieved cortex snippets to weave in. Each item: "
            "``{'source': '<uri>', 'text': '...'}``. Drafter cites by "
            "source URI inline."
        ),
    )


class UpdateDraftSectionTool(DonnaTool):
    name: ClassVar[str] = "update_draft_section"
    description: ClassVar[str] = (
        "Revise the active draft with a natural-language instruction. "
        "Drafter rewrites the full body (Sonnet) and bumps the version. "
        "Pass expected_version from your latest read."
    )
    args_model: ClassVar[type[BaseModel]] = UpdateDraftSectionArgs

    # Drafter intentionally accepts tainted snippets — its whole job is
    # to weave retrieved context (which IS external content) into a
    # draft body. The DrafterNode prompt frames context_snippets as
    # data, not instructions. taint_safe is True because the tool owns
    # the sanitization contract internally (see prompts.DRAFTER_SYSTEM).
    taint_safe: ClassVar[bool] = True
    timeout_s: ClassVar[int] = 180  # long-body Sonnet pass can take 60-120s

    def __init__(self, drafter: DrafterNode | None = None) -> None:
        self._drafter = drafter or DrafterNode()

    def run(self, args: UpdateDraftSectionArgs, ctx: ToolContext) -> ToolResult:
        with transaction.atomic():
            draft = (
                Artifact.objects
                .select_for_update()
                .filter(channel=ctx.channel, status=Artifact.Status.DRAFTING)
                .first()
            )
            if draft is None:
                return ToolResult.fail(
                    "No active draft. Call create_draft first."
                )
            if args.expected_version != draft.version:
                return ToolResult.fail(
                    f"Draft at v{draft.version}, you expected "
                    f"v{args.expected_version} — call read_draft and "
                    f"reissue with the fresh version."
                )

            out = self._drafter.revise(
                current=draft.body,
                instruction=args.instruction,
                context=args.context_snippets,
                title=draft.title,
                target_doc_type=draft.target_doc_type,
            )

            draft.body = out.markdown
            draft.version += 1
            draft.modified_by = ctx.user
            draft.save(update_fields=["body", "version", "updated_at", "modified_by"])

        _broadcast_doc_updated(ctx.channel.id, draft, action="updated")

        # Plan 13 §6.1 — refresh sibling status artifact in the
        # background so the team can read "where we are" without
        # scanning the whole body. Best-effort; failure is silent.
        try:
            from donna.chat.agents.magicdocs.draft_status_updater import (
                update_draft_status_doc,
            )
            update_draft_status_doc.delay(str(draft.id))
        except Exception:  # noqa: BLE001
            pass

        return ToolResult(payload={
            "artifact_id": str(draft.id),
            "version":     draft.version,
            "summary":     out.summary,
        })


# ── FinalizeDraftTool ──────────────────────────────────────────────────


class FinalizeDraftArgs(BaseModel):
    title: str = Field(
        default="",
        description=(
            "Final title for the cortex entity. Defaults to the draft's "
            "current title."
        ),
    )


class FinalizeDraftTool(DonnaTool):
    name: ClassVar[str] = "finalize_draft"
    description: ClassVar[str] = (
        "Lint the active draft and, on pass, persist it as a cortex "
        "doc entity. Returns the new entity_id. On lint reject, returns "
        "the rejection codes so you can fix and retry update_draft_section."
    )
    args_model: ClassVar[type[BaseModel]] = FinalizeDraftArgs
    taint_safe: ClassVar[bool] = True
    timeout_s: ClassVar[int] = 240  # linter + create_entity + embedding hop

    def run(self, args: FinalizeDraftArgs, ctx: ToolContext) -> ToolResult:
        draft = (
            Artifact.objects
            .filter(channel=ctx.channel, status=Artifact.Status.DRAFTING)
            .first()
        )
        if draft is None:
            return ToolResult.fail(
                "No active draft to finalize. Call create_draft first."
            )
        if not (draft.body or "").strip():
            return ToolResult.fail(
                "Draft body is empty. Call update_draft_section at least "
                "once before finalizing."
            )

        svc = CortexService(current_user=ctx.user, company=ctx.workspace)

        doc_type = draft.target_doc_type or "other"
        body_md = _ensure_source_footer(draft.body, ctx.channel.id, draft.id)

        verdict = svc.linter_check(
            type="doc",
            body_md=body_md,
            extensions={"doc_type": doc_type},
            title=args.title or draft.title,
        )
        if not getattr(verdict, "ok", False):
            return ToolResult(payload={
                "rejected_codes": list(getattr(verdict, "codes", []) or []),
                "artifact_id":    str(draft.id),
                "version":        draft.version,
            })

        entity = svc.create_entity(
            type="doc",
            author="agent",
            source=f"donna://channel/{ctx.channel.id}/draft/{draft.id}",
            title=args.title or draft.title,
            body_md=body_md,
            extensions={"doc_type": doc_type},
        )

        with transaction.atomic():
            draft.status = Artifact.Status.FINALIZED
            draft.finalized_entity_id = entity.id
            draft.modified_by = ctx.user
            draft.save(update_fields=[
                "status", "finalized_entity_id", "updated_at", "modified_by",
            ])

        _broadcast_doc_updated(ctx.channel.id, draft, action="finalized")
        return ToolResult(payload={
            "entity_id":   str(entity.id),
            "artifact_id": str(draft.id),
            "version":     draft.version,
        })


def _ensure_source_footer(body_md: str, channel_id, draft_id: UUID) -> str:
    """Linter requires a ``Source:`` or ``Spawned by:`` footer.

    For agent drafts we synthesize one pointing back at the originating
    channel + draft document so cortex round-trips back to the
    conversation that produced the entity.
    """
    footer_marker = "Source:"
    if footer_marker in body_md:
        return body_md
    footer = (
        f"\n\n---\nSource: donna://channel/{channel_id}/draft/{draft_id}\n"
    )
    return body_md.rstrip() + footer
