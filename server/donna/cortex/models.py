"""
Cortex entities — aligned with the
**Cortex Universal Silver Specification v1 (rev 3)**.

One normalised row per ingested OR curated artifact. Twelve `type`
values (closed Literal — see ``donna.cortex.schemas.EntityType``).

Schema invariants:

- Source of truth: per spec §14, files in ``SilverStorage`` are the
  canonical store; Postgres is a derived index that can be rebuilt at
  any time. ``cortex_entities`` is therefore the **index**, not the
  authority — but its shape mirrors ``SilverEntity`` 1-1 for cheap
  query plans.
- ``content_hash`` is unique per ``(workspace, content_hash)`` —
  idempotent re-writes.
- Nine edge fields live on the row (six forward + three reverse;
  see spec §4). All bidirectional edges are maintained atomically by
  ``CortexEntity.objects.save_with_reverse_edges`` (custom manager).
- ``client_id`` / ``project_id`` form the scope boundary contract
  (spec §6) — clustering NEVER traverses them.
"""
from __future__ import annotations

import uuid

from django.core.files.storage import default_storage
from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField

from donna.core.db.models import TimestampsMixin
from donna.cortex.managers import CortexEntityManager


def _body_upload_path(instance: "CortexEntity", filename: str) -> str:
    """Canonical body path under SilverStorage (`default_storage`).

    Layout: ``cortex/<workspace_id>/<type>/<entity_id>.md``. Mirrors
    spec §9 "Universal Folder Structure" intent — one file per entity,
    addressable by id.
    """
    return f"cortex/{instance.workspace_id}/{instance.type}/{instance.id}.md"


class CortexEntity(TimestampsMixin):
    """One normalised entity in the Cortex layer (Silver tier)."""

    # ── Closed type taxonomy (12 values; see spec §3) ───────────────
    class Type(models.TextChoices):
        # Accrued — connectors write automatically
        MEETING = "meeting", _("Meeting")
        EMAIL = "email", _("Email")
        CHAT = "chat", _("Chat")
        DOC = "doc", _("Document")
        TICKET = "ticket", _("Ticket")
        CLIP = "clip", _("Web clip")
        NOTE = "note", _("Note")
        # Curated — human/agent authored
        PERSON = "person", _("Person")
        ORG = "org", _("Organisation")
        PROJECT = "project", _("Project")
        CONCEPT = "concept", _("Concept")
        DECISION = "decision", _("Decision (ADR)")

    class Author(models.TextChoices):
        DONNA = "donna", _("Donna")
        HUMAN = "human", _("Human")
        AGENT = "agent", _("Agent")

    class Confidence(models.TextChoices):
        HIGH = "high", _("High")
        MEDIUM = "medium", _("Medium")
        LOW = "low", _("Low")

    # ── Identity ────────────────────────────────────────────────────
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    type = models.CharField(
        _("type"),
        max_length=16,
        choices=Type.choices,
    )

    # ── Authorship & provenance ─────────────────────────────────────
    author = models.CharField(
        _("author"),
        max_length=8,
        choices=Author.choices,
        default=Author.DONNA,
    )
    source = models.CharField(
        _("source URI"),
        max_length=512,
        help_text=_(
            "Provenance URI — e.g. fathom://meeting/<id>, "
            "gmail://thread/<id>, manual://, cortex://synth/<run>."
        ),
    )
    bronze_storage_key = models.CharField(
        _("bronze storage key"),
        max_length=500,
        blank=True,
        default="",
        help_text=_("Pointer to raw bronze blob in default_storage."),
    )
    content_hash = models.CharField(
        _("content hash"),
        max_length=64,
        help_text=_("sha256(body_md). Drives idempotency."),
    )

    # ── Temporal ────────────────────────────────────────────────────
    # ``synthesized_at`` is aliased to ``created_at`` (TimestampsMixin);
    # exposed via property below.
    occurred_at = models.DateTimeField(
        _("occurred at"),
        help_text=_("When the source event happened."),
    )

    # ── Scope (boundary contract — spec §6) ─────────────────────────
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="cortex_entities",
        related_query_name="cortex_entity",
    )
    # ``client_id`` and ``project_id`` reference other CortexEntity
    # rows (typed ``org`` and ``project`` respectively), but the
    # foreign-key constraint is omitted to avoid circular ordering at
    # write time — the row may reference a still-uncreated client.
    client_id = models.UUIDField(
        _("client id"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("UUID of the client `org` row. NULL = workspace-owner content."),
    )
    project_id = models.UUIDField(
        _("project id"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("UUID of the `project` row. NULL only if client_id is also NULL."),
    )

    # ── Topical (clustering) ────────────────────────────────────────
    cluster_id = models.UUIDField(
        _("cluster id"),
        null=True,
        blank=True,
        db_index=True,
    )
    doc_embedding = VectorField(
        _("doc embedding"),
        dimensions=384,
        null=True,
        blank=True,
        help_text=_("BGE-small 384-dim embedding."),
    )

    # ── Confidence + decay ──────────────────────────────────────────
    confidence = models.CharField(
        _("confidence"),
        max_length=8,
        choices=Confidence.choices,
        default=Confidence.HIGH,
    )
    last_synthesized = models.DateField(
        _("last synthesized"),
        null=True,
        blank=True,
        help_text=_(
            "Date this entity was last (re)synthesised. Drives "
            "confidence decay (R8) and resynth triggers (R6)."
        ),
    )

    # ── Content ─────────────────────────────────────────────────────
    title = models.CharField(_("title"), max_length=500)
    # The rendered markdown body lives in SilverStorage (S3 /
    # filesystem / GCS / Azure — per ``STORAGES['default']``). Postgres
    # only carries the path pointer + a byte-size stat. Lazy-fetch the
    # body via ``load_body()``.
    body = models.FileField(
        _("body markdown"),
        upload_to=_body_upload_path,
        storage=default_storage,
        max_length=500,
        blank=True,
        help_text=_(
            "Rendered markdown body stored in SilverStorage. Verbatim "
            "source content + Source: footer. Read via `load_body()`."
        ),
    )
    body_byte_size = models.IntegerField(
        _("body byte size"),
        default=0,
        help_text=_("Cheap byte-size stat; avoids opening the file."),
    )

    # ── Edges — forward (6 types; spec §4) ──────────────────────────
    entity_refs = models.JSONField(
        _("entity refs"),
        default=list,
        blank=True,
        help_text=_("UUIDs of curated entities mentioned (person/org/concept/project/decision)."),
    )
    sources = models.JSONField(
        _("sources"),
        default=list,
        blank=True,
        help_text=_("UUIDs of entities that informed this one."),
    )
    cross_refs = models.JSONField(
        _("cross refs"),
        default=list,
        blank=True,
        help_text=_("Related entities in the same (workspace, client, project) scope."),
    )
    supersedes = models.JSONField(
        _("supersedes"),
        default=list,
        blank=True,
        help_text=_("Explicit replacement chain (same type)."),
    )
    parent = models.UUIDField(
        _("parent"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Parent entity id (e.g. email from thread, clip from meeting)."),
    )
    related = models.JSONField(
        _("related"),
        default=list,
        blank=True,
        help_text=_("Curated-to-curated cross-link only (person↔org, concept↔concept)."),
    )

    # ── Edges — reverse (auto-maintained by repository) ─────────────
    applied_in = models.JSONField(
        _("applied in"),
        default=list,
        blank=True,
        help_text=_("UUIDs of entities citing this one (reverse of sources)."),
    )
    superseded_by = models.UUIDField(
        _("superseded by"),
        null=True,
        blank=True,
        help_text=_("Newer entity that replaced this (reverse of supersedes)."),
    )
    contradicts = models.JSONField(
        _("contradicts"),
        default=list,
        blank=True,
        help_text=_("Linter-detected conflicting entities (auto-populated)."),
    )

    # ── Per-type extensions (Pydantic-validated) ────────────────────
    extensions = models.JSONField(
        _("extensions"),
        default=dict,
        blank=True,
        help_text=_("Per-type Pydantic-validated extension dict."),
    )

    objects = CortexEntityManager()

    class Meta:
        db_table = "cortex_entities"
        verbose_name = _("Cortex entity")
        verbose_name_plural = _("Cortex entities")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "content_hash"],
                name="uq_cortex_entity_ws_hash",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "type", "-occurred_at"],
                name="cortex_entity_type_time",
            ),
            models.Index(
                fields=["workspace", "client_id", "project_id"],
                name="cortex_entity_scope",
            ),
        ]
        ordering = ["-occurred_at", "-created_at"]

    # ── Conveniences ────────────────────────────────────────────────

    @property
    def synthesized_at(self):
        """Alias for ``created_at`` matching the spec field name."""
        return self.created_at

    def load_body(self) -> str:
        """Lazy fetch of the rendered markdown body from SilverStorage.

        Returns the empty string when the FileField is unset (newly
        constructed in-memory entity).
        """
        if not self.body:
            return ""
        with self.body.open("rb") as f:
            return f.read().decode("utf-8")

    def __str__(self) -> str:
        return f"{self.type}: {self.title}"

    def __repr__(self) -> str:
        return (
            f"<CortexEntity: workspace={self.workspace_id} "
            f"type={self.type!r} id={self.id}>"
        )
