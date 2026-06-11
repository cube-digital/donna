"""
CortexWriter — facade orchestrator for Subsystems 1-5.

Aligned with **Cortex Universal Silver Specification v1 (rev 3)**.

The orchestrator owns no domain logic; each of the 11 steps delegates
to one collaborator. Default DI fills every collaborator with a
spec-conforming implementation.

Pipeline steps (see spec §5 + this implementation):

1.  OCR / markdownify
2.  Type resolve + TypeSpec lookup
3.  Deterministic frontmatter fill from adapter metadata
4.  Fitter fallback (HaikuFitter) when nav fields missing
5.  Embed + cluster_assign (scoped to workspace/client/project tuple)
6.  Folder placement (per Universal Folder Structure §9)
7.  Render body via Jinja TypeSpec template
8.  Build entity (unsaved)
9.  Entity extraction + resolution → ``entity_refs[]``
10. Linter gate (R1-R10 + spec §7.2 hard rejects)
11. Atomic persist (entity + reverse-edge updates in one txn)
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.files.storage import default_storage
from django.utils.text import slugify

from donna.cortex.clustering import HDBSCANClusterer, Scope
from donna.cortex.embeddings import BGESmallEmbedder
from donna.cortex.entities import (
    CompositeExtractor,
    DeterministicResolver,
    EntityExtractor,
    EntityResolver,
    ExtractContext,
    GLiNERExtractor,
    ProviderMetadataExtractor,
)
from donna.cortex.linter import FrontmatterLinter
from donna.cortex.models import CortexEntity
from donna.cortex.ocr import OCRService
from donna.cortex.registry import TemplateRegistry, TypeSpec
from donna.cortex.template_engine import (
    NoOpFitter,
    TemplateEngine,
    TemplateFitter,
)


if TYPE_CHECKING:
    from donna.integrations.models import DeliveryPackage


logger = logging.getLogger(__name__)


# Map connector ``provider_item_type`` → canonical Silver type.
# Connectors emit their own vocab (Fathom: "meeting", Drive: "file"); the
# pipeline normalises here so Cortex only sees the 12 canonical types.
PROVIDER_TYPE_MAP: dict[str, str] = {
    "meeting": "meeting",
    "email": "email",
    "chat": "chat",
    "message_thread": "chat",
    "file": "doc",
    "doc": "doc",
    "ticket": "ticket",
    "clip": "clip",
    "note": "note",
}


# Provider name → source URI scheme.
PROVIDER_URI_SCHEME: dict[str, str] = {
    "fathom": "fathom",
    "gmail": "gmail",
    "google_mail": "gmail",
    "google_drive": "gdrive",
    "drive": "gdrive",
    "linear": "linear",
    "jira": "jira",
    "github": "github",
    "slack": "slack",
    "whatsapp": "whatsapp",
}


class CortexWriter:
    """Single entry point. ``write(dp)`` walks the 11-step pipeline."""

    def __init__(
        self,
        *,
        ocr: OCRService | None = None,
        embedder=None,
        clusterer=None,
        extractor: EntityExtractor | None = None,
        resolver: EntityResolver | None = None,
        registry: TemplateRegistry | None = None,
        engine: TemplateEngine | None = None,
        fitter: TemplateFitter | None = None,
        linter: FrontmatterLinter | None = None,
        enable_gliner: bool = False,
        enable_embeddings: bool = False,
    ) -> None:
        self.ocr = ocr or OCRService()
        self.embedder = (
            embedder
            if embedder is not None
            else (BGESmallEmbedder() if enable_embeddings else None)
        )
        self.clusterer = (
            clusterer
            if clusterer is not None
            else (HDBSCANClusterer() if enable_embeddings else None)
        )
        if extractor is not None:
            self.extractor = extractor
        else:
            chain: list[EntityExtractor] = [ProviderMetadataExtractor()]
            if enable_gliner:
                chain.append(GLiNERExtractor())
            self.extractor = CompositeExtractor(*chain)
        self.resolver = resolver or DeterministicResolver()
        self.registry = registry or TemplateRegistry()
        self.engine = engine or TemplateEngine()
        self.fitter = fitter or NoOpFitter()
        self.linter = linter or FrontmatterLinter()

    # ── main entry ──────────────────────────────────────────────────

    def write(self, dp: "DeliveryPackage") -> CortexEntity:
        # 1. OCR / markdownify ──────────────────────────────────────
        body_md = self._body_for(dp)

        # 2. Type resolve + TypeSpec ────────────────────────────────
        cortex_type = PROVIDER_TYPE_MAP.get(
            dp.provider_item_type, dp.provider_item_type
        )
        type_spec = self.registry.get(cortex_type)

        # 3. Deterministic frontmatter fill ─────────────────────────
        extensions = self._build_extensions(dp, type_spec)

        # 4. Fit fallback (Haiku) only when nav fields missing ──────
        if not self.linter.has_required_nav_fields(
            extensions, type_spec.nav_fields
        ):
            if type_spec.fit_model is not None:
                try:
                    fit = self.fitter.fit(body_md, type_spec.fit_model)
                    extensions = self._merge_fit(extensions, fit)
                except NotImplementedError:
                    pass

        # 5. Embed + cluster_assign ─────────────────────────────────
        # Per P0.14: embedder receives a sampled representation (per-type
        # window strategy declared on the TypeSpec), NOT the full body.
        # BGE-small context = 512 tokens ≈ ~1900 chars — sampling chosen
        # so contracts (signatures at the end) and meetings (decisions
        # late) keep their signal.
        scope = Scope(
            workspace_id=dp.workspace_id,
            client_id=None,  # set below once entity_refs resolved
            project_id=None,
        )
        embedding: list[float] | None = None
        cluster_id: UUID | None = None
        cluster_name: str | None = None
        if self.embedder is not None and self.clusterer is not None:
            embedding = self.embedder.embed_entity(
                title=dp.title or "Untitled",
                body_md=body_md,
                sampler=type_spec.embedding_sampler,
            )
            cluster_id, cluster_name = self.clusterer.assign(embedding, scope)
        extensions["cluster_name"] = cluster_name  # surfaced in body template

        # 6. Folder placement ───────────────────────────────────────
        client_slug, project_slug = self._scope_slugs(scope)
        parent_path = type_spec.folder_resolver.canonical_path(
            type=cortex_type,
            occurred_at=dp.occurred_at,
            extensions=extensions,
            client_slug=client_slug,
            project_slug=project_slug,
        )
        slug = self._build_slug(dp, body_md)
        extensions["parent_path"] = parent_path
        extensions["slug"] = slug

        # 7. Render body ────────────────────────────────────────────
        bronze_key = dp.storage_key
        source_uri = self._source_uri(dp)
        body_md_final = self.engine.render(
            type_spec,
            data=extensions,
            body_input=body_md,
            title=dp.title or "Untitled",
            occurred_at=dp.occurred_at,
            source_uri=source_uri,
            bronze_storage_key=bronze_key,
        )

        # 8. Build the entity (unsaved) ─────────────────────────────
        # Body lives in SilverStorage (P0.14). We carry the rendered
        # bytes in memory across steps 9-10; step 11 writes them out
        # via the FileField in the same atomic transaction.
        body_bytes = body_md_final.encode("utf-8")
        content_hash = hashlib.sha256(body_bytes).hexdigest()
        now = datetime.now(tz=timezone.utc)
        new_entity = CortexEntity(
            workspace_id=dp.workspace_id,
            type=cortex_type,
            author="donna",
            source=source_uri,
            bronze_storage_key=bronze_key,
            occurred_at=dp.occurred_at or now,
            client_id=scope.client_id,
            project_id=scope.project_id,
            cluster_id=cluster_id,
            doc_embedding=embedding,
            confidence="high",
            last_synthesized=now.date(),
            title=dp.title or "Untitled",
            body_byte_size=len(body_bytes),
            content_hash=content_hash,
            extensions=extensions,
        )

        # 9. Entity extraction + resolution → entity_refs[] ─────────
        context = ExtractContext(adapter_metadata=dp.metadata or {})
        candidates = self.extractor.extract(entity=new_entity, context=context)
        entity_refs: list[str] = []
        for candidate in candidates:
            target_id = self.resolver.resolve(candidate, scope)
            if str(target_id) not in entity_refs:
                entity_refs.append(str(target_id))
        new_entity.entity_refs = entity_refs

        # 10. Linter gate ───────────────────────────────────────────
        # body_md_final passed explicitly — entity.body FileField is
        # still unset at this point. Linter reads the in-memory body.
        self.linter.check(new_entity, body_md=body_md_final)

        # 11. Persist atomically ─────────────────────────────────────
        # Repository handles: INSERT row → save FileField body to
        # SilverStorage → reverse-edge updates, all inside one PG txn.
        # NOTE: ``applied_in[]`` reverse-edge for the entity_refs is
        # not maintained here — entity_refs target curated rows whose
        # ``applied_in[]`` is derived at read time (see §7 R9 + spec
        # §4 "Derived: touchpoints"). Only ``sources / supersedes /
        # contradicts`` carry strict reverse-edge writes.
        return CortexEntity.objects.save_with_reverse_edges(
            new_entity, body_bytes=body_bytes
        )

    # ── helpers ─────────────────────────────────────────────────────

    def _body_for(self, dp: "DeliveryPackage") -> str:
        try:
            with default_storage.open(dp.storage_key, "rb") as f:
                raw_bytes = f.read()
        except Exception:  # noqa: BLE001
            logger.exception(
                "cortex_storage_read_failed",
                extra={"storage_key": dp.storage_key},
            )
            return ""

        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            suffix = Path(dp.storage_key).suffix or ".bin"
            return self.ocr.extract(raw_bytes, suffix=suffix).text

        try:
            from donna.core.integrations import get as get_provider

            provider_cls = get_provider(dp.provider)
            provider = provider_cls()
            adapter = provider.adapter_for(raw)
            md = adapter.to_markdown()
            if md:
                return md
            text = adapter.to_text()
            if text:
                return text
        except Exception:  # noqa: BLE001
            logger.warning(
                "cortex_adapter_markdown_failed",
                extra={"provider": dp.provider, "dp_id": str(dp.id)},
                exc_info=True,
            )

        suffix = Path(dp.storage_key).suffix or ".json"
        return self.ocr.extract(raw_bytes, suffix=suffix).text

    def _build_extensions(
        self, dp: "DeliveryPackage", type_spec: TypeSpec
    ) -> dict:
        """Per-type deterministic fill from adapter metadata."""
        meta = dp.metadata or {}
        if type_spec.type == "meeting":
            return {
                "attendees": self._attendees(
                    meta.get("attendees") or meta.get("participants")
                ),
                "duration_min": meta.get("duration_min")
                or (
                    int(meta["duration_seconds"] / 60)
                    if isinstance(meta.get("duration_seconds"), (int, float))
                    else None
                ),
                "recording_url": meta.get("recording_url"),
            }
        if type_spec.type == "email":
            return {
                "thread_id": meta.get("thread_id"),
                "participants_emails": self._participants(
                    meta.get("participants_emails") or meta.get("recipients")
                ),
            }
        if type_spec.type == "chat":
            return {
                "channel": meta.get("channel") or "general",
                "participants": self._emails(meta.get("participants")),
            }
        if type_spec.type == "doc":
            return {
                "doc_type": meta.get("doc_type", "other"),
                "mime": meta.get("mime_type") or meta.get("mime"),
                "author_email": (
                    (meta.get("owner") or {}).get("email")
                    if isinstance(meta.get("owner"), dict)
                    else None
                ),
            }
        if type_spec.type == "ticket":
            return {
                "provider": meta.get("provider", "jira"),
                "external_id": meta.get("external_id", dp.provider_item_id),
                "status": meta.get("status", "open"),
                "assignees": meta.get("assignees", []),
                "parent_epic_id": meta.get("parent_epic_id"),
            }
        if type_spec.type == "clip":
            return {
                "url": meta.get("url", ""),
                "why_captured": meta.get("why_captured", ""),
                "captured_by": meta.get("captured_by"),
            }
        if type_spec.type == "note":
            return {
                "note_type": meta.get("note_type", "journal"),
                "why": meta.get("why"),
                "is_open_question": bool(meta.get("is_open_question", False)),
            }
        return {}

    @staticmethod
    def _attendees(items) -> list[dict]:
        out: list[dict] = []
        for item in items or []:
            if isinstance(item, dict):
                out.append(
                    {
                        "name": item.get("name"),
                        "email": item.get("email"),
                        "role": item.get("role"),
                    }
                )
            elif isinstance(item, str) and "@" in item:
                out.append({"name": item, "email": item, "role": None})
        return out

    @staticmethod
    def _participants(items) -> list[dict]:
        out: list[dict] = []
        for item in items or []:
            if isinstance(item, dict):
                out.append(
                    {
                        "name": item.get("name"),
                        "addr": item.get("addr") or item.get("email"),
                        "role": item.get("role"),
                    }
                )
            elif isinstance(item, str):
                out.append({"name": None, "addr": item, "role": "to"})
        return [p for p in out if p.get("addr")]

    @staticmethod
    def _emails(items) -> list[str]:
        if not items:
            return []
        out: list[str] = []
        for item in items:
            if isinstance(item, dict) and item.get("email"):
                out.append(item["email"])
            elif isinstance(item, str) and "@" in item:
                out.append(item)
        return out

    def _merge_fit(self, extensions: dict, fit_result) -> dict:
        try:
            payload = fit_result.model_dump()
        except AttributeError:
            payload = dict(fit_result)
        for key, value in payload.items():
            if extensions.get(key) in (None, "", [], {}):
                extensions[key] = value
        return extensions

    def _build_slug(self, dp: "DeliveryPackage", body_md: str) -> str:
        base = slugify(dp.title or "untitled") or "untitled"
        suffix = hashlib.sha1(body_md.encode()).hexdigest()[:8]
        date_prefix = ""
        if dp.occurred_at:
            occ = dp.occurred_at
            if isinstance(occ, datetime):
                date_prefix = f"{occ:%Y-%m-%d}-"
            elif isinstance(occ, str) and len(occ) >= 10:
                date_prefix = f"{occ[:10]}-"
        return f"{date_prefix}{base}-{suffix}"

    @staticmethod
    def _source_uri(dp: "DeliveryPackage") -> str:
        scheme = PROVIDER_URI_SCHEME.get(dp.provider, dp.provider)
        kind = PROVIDER_TYPE_MAP.get(
            dp.provider_item_type, dp.provider_item_type
        )
        return f"{scheme}://{kind}/{dp.provider_item_id}"

    def _scope_slugs(self, scope: Scope) -> tuple[str | None, str | None]:
        """Resolve ``client_id`` / ``project_id`` → folder slugs."""
        client_slug = None
        project_slug = None
        if scope.client_id is not None:
            client = CortexEntity.objects.filter(id=scope.client_id).first()
            if client:
                client_slug = (client.extensions or {}).get("slug")
        if scope.project_id is not None:
            project = CortexEntity.objects.filter(id=scope.project_id).first()
            if project:
                project_slug = (project.extensions or {}).get("slug")
        return client_slug, project_slug
