"""Cortex read tools — Q&A surface.

Four tools wrap CortexService:

- ``cortex_query`` — hybrid search (dense + keyword RRF) with metadata
  filters. Returns ranked entity headers with source URIs.
- ``read_entity`` — full entity body + edges by id.
- ``get_context`` — depth-bounded neighbor walk for follow-up questions.
- ``prepare_context`` — **macro tool** (docupal pattern, 2026-06-14):
  fans out cortex_query and top-N read_entity in parallel; returns a
  single digest. Cuts 2-3 loop rounds on fresh topics — the model
  doesn't have to walk query → read → maybe-read sequentially when it
  knows nothing about the topic yet.

System prompt steers usage: ``prepare_context`` first on unfamiliar
topics, then focused ``cortex_query`` / ``read_entity`` for follow-ups.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, Field

from donna.cortex.services import CortexService

from .base import DonnaTool, ToolContext, ToolResult


# ── cortex_query ────────────────────────────────────────────────────


class CortexQueryArgs(BaseModel):
    text: str = Field(description="Free-text query — what the user wants to know.")
    type: str | None = Field(
        default=None,
        description=(
            "Optional entity type filter: meeting, email, chat, doc, ticket, "
            "clip, note, person, org, project, concept, decision."
        ),
    )
    doc_type: str | None = Field(
        default=None,
        description="When type=doc, optionally filter by doc_type (spec, contract, runbook, …).",
    )
    client_id: UUID | None = Field(default=None, description="Restrict to a client scope.")
    project_id: UUID | None = Field(default=None, description="Restrict to a project scope.")
    relationship: str | None = Field(
        default=None,
        description=(
            "Restrict to entities scoped to an org of this relationship: "
            "'client' (paying engagements), 'partner' (co-build/co-sell), "
            "'vendor' (invoices/bookings/SaaS receipts), 'peer' (industry "
            "contacts). Do NOT conflate — 'list our clients' means client only."
        ),
    )
    limit: int = Field(default=8, ge=1, le=25, description="Max results to return.")


class CortexQueryTool(DonnaTool):
    name: ClassVar[str] = "cortex_query"
    description: ClassVar[str] = (
        "Search the company knowledge layer (cortex) — meetings, emails, "
        "docs, tickets, people, decisions, projects. Metadata filters "
        "(type, doc_type, client_id, project_id, relationship) apply BEFORE "
        "similarity. Every result carries `source` — cite it in your answer."
    )
    args_model: ClassVar[type[BaseModel]] = CortexQueryArgs
    timeout_s: ClassVar[int] = 60
    taint_safe: ClassVar[bool] = True

    def announce(self, args: CortexQueryArgs) -> str:
        return f"Searching cortex for “{args.text[:60]}”…"

    def run(self, args: CortexQueryArgs, ctx: ToolContext) -> ToolResult:
        svc = CortexService(current_user=ctx.user, company=ctx.workspace)
        hits = svc.query(
            text=args.text,
            type=args.type,
            doc_type=args.doc_type,
            client_id=args.client_id,
            project_id=args.project_id,
            relationship=args.relationship,
            limit=args.limit,
        )
        return ToolResult(payload={"results": [h.summary() for h in hits]})


# ── read_entity ─────────────────────────────────────────────────────


class ReadEntityArgs(BaseModel):
    entity_id: UUID = Field(description="The entity id returned by cortex_query.")
    include_body: bool = Field(
        default=True,
        description="Return the full markdown body. False = header + edges only.",
    )


class ReadEntityTool(DonnaTool):
    name: ClassVar[str] = "read_entity"
    description: ClassVar[str] = (
        "Read a single cortex entity by id. Use after cortex_query to get "
        "the full body for citation. include_body=False is cheaper when "
        "you only need the title/edges."
    )
    args_model: ClassVar[type[BaseModel]] = ReadEntityArgs
    timeout_s: ClassVar[int] = 30
    taint_safe: ClassVar[bool] = True

    def announce(self, args: ReadEntityArgs) -> str:
        return f"Reading entity {str(args.entity_id)[:8]}…"

    def run(self, args: ReadEntityArgs, ctx: ToolContext) -> ToolResult:
        svc = CortexService(current_user=ctx.user, company=ctx.workspace)
        card = svc.read_entity(args.entity_id, include_body=args.include_body)
        if card is None:
            return ToolResult.fail(f"entity {args.entity_id} not found in this workspace")
        return ToolResult(payload=card.as_dict())


# ── get_context ─────────────────────────────────────────────────────


class GetContextArgs(BaseModel):
    entity_id: UUID = Field(description="Seed entity to expand around.")
    depth: int = Field(
        default=1,
        ge=1,
        le=2,
        description="1 = direct neighbors. 2 = neighbors of neighbors (capped).",
    )


class GetContextTool(DonnaTool):
    name: ClassVar[str] = "get_context"
    description: ClassVar[str] = (
        "Expand around an entity via its entity_refs + sources edges. "
        "Use when the answer requires connecting multiple cortex rows "
        "(meeting → decision → org)."
    )
    args_model: ClassVar[type[BaseModel]] = GetContextArgs
    timeout_s: ClassVar[int] = 45
    taint_safe: ClassVar[bool] = True

    def announce(self, args: GetContextArgs) -> str:
        return f"Walking context (depth={args.depth}) around {str(args.entity_id)[:8]}…"

    def run(self, args: GetContextArgs, ctx: ToolContext) -> ToolResult:
        svc = CortexService(current_user=ctx.user, company=ctx.workspace)
        cards = svc.get_context(args.entity_id, depth=args.depth)
        return ToolResult(payload={"neighbors": [c.as_dict() for c in cards]})


# ── prepare_context (macro) ─────────────────────────────────────────


class PrepareContextArgs(BaseModel):
    topic: str = Field(
        description=(
            "Plain English description of what the user wants context on — "
            "a person, client, project, document name, or general subject."
        ),
    )
    type: str | None = Field(
        default=None,
        description="Optional entity type filter passed through to cortex_query.",
    )
    client_id: UUID | None = Field(default=None, description="Optional client scope.")
    project_id: UUID | None = Field(default=None, description="Optional project scope.")
    top_n_bodies: int = Field(
        default=3,
        ge=1,
        le=5,
        description="How many top hits to fully read alongside the query result.",
    )


class PrepareContextTool(DonnaTool):
    """Macro tool — query + top-N read in parallel.

    Call FIRST when a conversation turns to a new topic and the agent
    has no prior cortex context loaded. Single round-trip replaces the
    classic query → read → maybe-read sequential walk.
    """

    name: ClassVar[str] = "prepare_context"
    description: ClassVar[str] = (
        "Call FIRST when a conversation turns to a new topic. Runs a "
        "cortex_query and reads the top hits' full bodies in parallel, "
        "returning one digest. After this, use focused tools "
        "(cortex_query / read_entity / get_context) for follow-ups."
    )
    args_model: ClassVar[type[BaseModel]] = PrepareContextArgs
    timeout_s: ClassVar[int] = 300  # 1 query + N parallel body reads + RTT
    taint_safe: ClassVar[bool] = True

    def announce(self, args: PrepareContextArgs) -> str:
        return f"Preparing context on “{args.topic[:60]}”…"

    def run(self, args: PrepareContextArgs, ctx: ToolContext) -> ToolResult:
        svc = CortexService(current_user=ctx.user, company=ctx.workspace)
        # Phase 1 — query (single shot; returns ranked headers).
        hits = svc.query(
            text=args.topic,
            type=args.type,
            client_id=args.client_id,
            project_id=args.project_id,
            limit=8,
        )
        if not hits:
            return ToolResult(payload={
                "topic": args.topic,
                "results": [],
                "top_documents": [],
                "note": "No cortex hits — answer honestly that nothing matches.",
            })

        # Phase 2 — fan-out read_entity on top N. Parallel because each
        # body-read is independent + bounded by storage I/O.
        top = hits[: args.top_n_bodies]
        with ThreadPoolExecutor(max_workers=max(1, len(top))) as pool:
            bodies = list(
                pool.map(
                    lambda h: svc.read_entity(h.id, include_body=True),
                    top,
                )
            )

        return ToolResult(payload={
            "topic": args.topic,
            "results": [h.summary() for h in hits],
            "top_documents": [b.as_dict() for b in bodies if b is not None],
        })
