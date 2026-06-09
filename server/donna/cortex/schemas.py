"""
Pydantic models for the Cortex layer — aligned with the
**Cortex Universal Silver Specification v1 (rev 3)**.

Single canonical ``SilverEntity`` model for all 12 types (no Gold split).
Lifecycle distinction (accrued vs curated) is captured via
``type`` + ``author`` + per-type ``extensions`` discriminator.

Used by:

- ``FrontmatterLinter`` at write time (Pydantic gate + R1-R10).
- ``CortexWriter`` step 3 / step 8 (frontmatter build + entity build).
- ``MCP API`` request/response payloads (P9, locked surface).

See `Cortex Universal Silver Specification.md` §§3-5 in the vault.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Closed taxonomies (locked — amendments require ADR) ────────────


EntityType = Literal[
    # Accrued — Donna connectors write automatically (high volume)
    "meeting",
    "email",
    "chat",
    "doc",
    "ticket",
    "clip",
    "note",
    # Curated — human-written or agent-synthesised (low volume, high authority)
    "person",
    "org",
    "project",
    "concept",
    "decision",
]


AuthorKind = Literal["donna", "human", "agent"]


ConfidenceKind = Literal["high", "medium", "low"]


# Sub-discriminators ────────────────────────────────────────────────


DocType = Literal[
    "offer",
    "requirements",
    "spec",
    "contract",
    "handover",
    "technical_analysis",
    "internal_memo",
    "presentation",
    "signed_document",
    "runbook",
    "plan",
    "integration_spec",
    "checkpoint",
    "architecture_note",
    "design_note",
    "other",
]


NoteType = Literal[
    "brainstorm",
    "checkpoint",
    "journal",
    "action_item",
    "open_question",
]


TicketProvider = Literal[
    "jira",
    "linear",
    "github",
    "asana",
    "clickup",
]


TicketStatus = str  # provider-specific; spec leaves open


OrgRelationship = Literal[
    "client",
    "vendor",
    "partner",
    "competitor",
    "internal",
    "self",  # exactly one per workspace — the workspace owner
]


ProjectStatus = Literal["proposed", "active", "shipped", "archived"]


ConceptMaturity = Literal["seed", "growing", "evergreen"]


ADRStatus = Literal["proposed", "accepted", "superseded"]


# ── Reusable sub-models ────────────────────────────────────────────


class Attendee(BaseModel):
    """Meeting attendee — emitted by Fathom/Zoom adapters."""

    name: str | None = None
    email: str | None = None
    role: str | None = None  # host, organiser, attendee, …


class Participant(BaseModel):
    """Email/chat participant."""

    name: str | None = None
    addr: str
    role: Literal["from", "to", "cc", "bcc", "host", "member"] | None = None


# ── Type-specific extensions (per spec §5.1) ───────────────────────


class MeetingExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    attendees: list[Attendee] = Field(default_factory=list)
    duration_min: int | None = None
    recording_url: str | None = None
    # connector-specific (fathom_meeting_id, zoom_meeting_uuid, …)


class EmailExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    thread_id: str | None = None
    participants_emails: list[Participant] = Field(default_factory=list)
    # connector-specific (gmail_message_ids, outlook_conversation_id, …)


class ChatExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    channel: str | None = None
    participants: list[str] = Field(default_factory=list)


class DocExtensions(BaseModel):
    """REQUIRED: ``doc_type``. R-hard-reject: ``MISSING_REQUIRED_EXTENSION``."""

    model_config = ConfigDict(extra="allow")
    doc_type: DocType
    mime: str | None = None
    author_email: str | None = None


class TicketExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider: TicketProvider
    external_id: str
    status: TicketStatus
    assignees: list[str] = Field(default_factory=list)
    parent_epic_id: str | None = None


class ClipExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: str
    why_captured: str
    captured_by: str | None = None


class NoteExtensions(BaseModel):
    """REQUIRED: ``note_type``. R-hard-reject: ``MISSING_REQUIRED_EXTENSION``."""

    model_config = ConfigDict(extra="allow")
    note_type: NoteType
    why: str | None = None
    is_open_question: bool = False  # for derived view


class PersonExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    full_name: str | None = None
    primary_email: str | None = None
    role: str | None = None
    employer_org_id: UUID | None = None
    cross_workspace_aliases: list[str] = Field(default_factory=list)


class OrgExtensions(BaseModel):
    """``relationship: 'self'`` reserved for the workspace owner's own org."""

    model_config = ConfigDict(extra="allow")
    legal_name: str | None = None
    email_domains: list[str] = Field(default_factory=list)
    industry: str | None = None
    relationship: OrgRelationship = "client"


class ProjectExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: ProjectStatus = "active"
    target_ship_date: date | None = None
    repo_url: str | None = None
    deployed_url: str | None = None
    stack: list[str] = Field(default_factory=list)


class ConceptExtensions(BaseModel):
    """Cross-project. R-hard-reject: ``INSUFFICIENT_EVIDENCE`` if sources<2."""

    model_config = ConfigDict(extra="allow")
    aliases: list[str] = Field(default_factory=list)
    domain: str | None = None
    maturity: ConceptMaturity = "seed"


class DecisionExtensions(BaseModel):
    """REQUIRED: ``context_sources``. R-hard-reject: ``MISSING_REQUIRED_EXTENSION``."""

    model_config = ConfigDict(extra="allow")
    adr_status: ADRStatus = "proposed"
    deciders: list[UUID] = Field(default_factory=list)
    context_sources: list[UUID] = Field(default_factory=list)
    supersedes_adr: UUID | None = None


# ── SilverEntity canonical Pydantic model ──────────────────────────


class SilverEntity(BaseModel):
    """The single canonical entity model. See spec §5."""

    model_config = ConfigDict(extra="forbid")

    # ── Identity ────────────────────────────────────────────────────
    id: UUID
    type: EntityType

    # ── Authorship & provenance (anti-hallucination) ────────────────
    author: AuthorKind
    source: str  # URI: fathom://meeting/<id>, gmail://thread/<id>, manual://, cortex://synth/<run>
    bronze_storage_key: Optional[str] = None
    content_hash: str  # SHA256(body_md)

    # ── Temporal ────────────────────────────────────────────────────
    occurred_at: datetime
    synthesized_at: datetime

    # ── Scope (boundary contract) ───────────────────────────────────
    workspace_id: UUID
    client_id: Optional[UUID] = None  # boundary 1 — NEVER traversed by clustering
    project_id: Optional[UUID] = None  # boundary 2 — null only if client_id is null

    # ── Topical ─────────────────────────────────────────────────────
    cluster_id: Optional[UUID] = None
    embedding: list[float] = Field(default_factory=list)  # 384-dim BGE-small default

    # ── Edges — forward (9 total, see spec §4) ──────────────────────
    entity_refs: list[UUID] = Field(default_factory=list)  # mentions of curated rows
    sources: list[UUID] = Field(default_factory=list)
    cross_refs: list[UUID] = Field(default_factory=list)  # intra-scope only (R4)
    supersedes: list[UUID] = Field(default_factory=list)
    parent: Optional[UUID] = None
    related: list[UUID] = Field(default_factory=list)  # curated↔curated only

    # ── Edges — reverse (auto-maintained by repository) ─────────────
    applied_in: list[UUID] = Field(default_factory=list)
    superseded_by: Optional[UUID] = None
    contradicts: list[UUID] = Field(default_factory=list)  # auto by linter

    # ── Confidence & decay ──────────────────────────────────────────
    confidence: ConfidenceKind = "high"
    last_synthesized: date

    # ── Content ─────────────────────────────────────────────────────
    title: str
    body_md: str

    # ── Per-type extensions ─────────────────────────────────────────
    extensions: dict[str, Any] = Field(default_factory=dict)


# ── Type → Extensions model registry ───────────────────────────────


EXTENSION_MODELS: dict[str, type[BaseModel]] = {
    "meeting": MeetingExtensions,
    "email": EmailExtensions,
    "chat": ChatExtensions,
    "doc": DocExtensions,
    "ticket": TicketExtensions,
    "clip": ClipExtensions,
    "note": NoteExtensions,
    "person": PersonExtensions,
    "org": OrgExtensions,
    "project": ProjectExtensions,
    "concept": ConceptExtensions,
    "decision": DecisionExtensions,
}
