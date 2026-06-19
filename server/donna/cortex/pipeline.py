"""
CortexPipeline — facade orchestrator for Subsystems 1-5.

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
from donna.cortex.registry import TemplateRegistry, TypeSpec
from donna.cortex.template_engine import (
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
    "drive_file": "doc",          # Drive connector emits drive_file
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


class CortexPipeline:
    """Single entry point. ``write(dp)`` walks the 11-step pipeline."""

    def __init__(
        self,
        *,
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
        # OCR removed 2026-06-15 — cortex.ocr.OCRService deleted; the
        # .extracted.md sidecar covers normal-case body resolution and
        # tier-3 fallback returns "" on parse failure (linter then rejects
        # via MISSING_SOURCE_FOOTER, surfacing the bad ingest).
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
        # Fitter is opt-in (2026-06-12): None = skip nav-field LLM fill.
        # Step 4 guards with ``if self.fitter and type_spec.fit_model``.
        self.fitter = fitter
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
        # Adapters emit a typed CanonicalEntity whose extensions dict
        # is Pydantic-validated at the connector boundary. Pipeline
        # reads that directly — no legacy fallback. DPs missing a
        # canonical payload are pre-Phase-2 and must be re-ingested.
        extensions = self._extensions_from_canonical(dp)

        # 3b. doc_type ladder — tier A heuristic, then tier B kNN.
        # A (free, deterministic) fires on the obvious ~40-60%; B
        # (cheap, vector-only) fires on the next ~20-30% before tier C
        # (Haiku, in step 4 via HaikuFitter) gets called for the rest.
        if cortex_type == "doc" and not (extensions.get("doc_type") and extensions["doc_type"] != "other"):
            from donna.cortex.doc_classifier import (
                HeuristicDocClassifier,
                KNNDocClassifier,
            )

            # Tier A — heuristic.
            verdict = HeuristicDocClassifier().classify(
                filename=(dp.metadata or {}).get("filename", "") or dp.title or "",
                mime=(dp.metadata or {}).get("mime_type")
                     or (dp.metadata or {}).get("mime", "") or "",
                body_md=body_md,
            )
            # Tier B — kNN over pgvector head embeddings (Phase 4c).
            if verdict.doc_type is None and self.embedder is not None:
                verdict = KNNDocClassifier(embedder=self.embedder).classify(
                    workspace_id=dp.workspace_id,
                    title=dp.title or "",
                    body_md=body_md,
                )
            if verdict.doc_type:
                extensions["doc_type"] = verdict.doc_type
                extensions["doc_type_basis"] = verdict.basis
                extensions["doc_type_confidence"] = verdict.confidence

        # 4. Fit fallback (Haiku) only when nav fields missing ──────
        # Guard pattern (2026-06-12): explicit fitter presence check
        # replaces the try/except NotImplementedError that previously
        # silenced real bugs in custom fitters.
        if not self.linter.has_required_nav_fields(
            extensions, type_spec.nav_fields
        ):
            if self.fitter is not None and type_spec.fit_model is not None:
                fit = self.fitter.fit(
                    body_md,
                    type_spec.fit_model,
                    sampler=type_spec.embedding_sampler,
                )
                extensions = self._merge_fit(extensions, fit)

        # 5. Embed + cluster_assign ─────────────────────────────────
        # Scope ladder T0 → T1 (Phase 4c, 2026-06-15). Run BEFORE
        # cluster assign so clustering bounds within (workspace,
        # client, project) honours the suggestion.
        from donna.cortex.scope import suggest_scope

        candidate_domains: list[str] = []
        meta = dp.metadata or {}
        for src in ("host", "sender", "owner"):
            obj = meta.get(src)
            if isinstance(obj, dict) and obj.get("email"):
                candidate_domains.append(obj["email"].split("@", 1)[-1].lower())
        for src in ("participants", "recipients", "to", "cc", "attendees"):
            for item in meta.get(src) or []:
                addr = item.get("email") if isinstance(item, dict) else (item if isinstance(item, str) else None)
                if addr and "@" in addr:
                    candidate_domains.append(addr.split("@", 1)[-1].lower())

        suggestion = suggest_scope(
            workspace_id=dp.workspace_id,
            metadata=dp.metadata,
            candidate_domains=candidate_domains,
        )
        scope_client = suggestion.client_id if suggestion.auto_apply else None
        scope_project = suggestion.project_id if suggestion.auto_apply else None
        if not suggestion.auto_apply and suggestion.basis != "none":
            # Surface to the bulk-confirm queue via extensions slot
            # (Phase 5 vault renderer reads this).
            extensions["suggested_scope"] = {
                "client_id": str(suggestion.client_id) if suggestion.client_id else None,
                "project_id": str(suggestion.project_id) if suggestion.project_id else None,
                "confidence": suggestion.confidence,
                "basis": suggestion.basis,
            }

        scope = Scope(
            workspace_id=dp.workspace_id,
            client_id=scope_client,
            project_id=scope_project,
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
        # folder_resolver is a plain callable (FolderFn) since the
        # 2026-06-14 refactor — no more .canonical_path indirection.
        client_slug, project_slug = self._scope_slugs(scope)
        parent_path = type_spec.folder_resolver(
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

        # 8½. Two-tier dedup (Phase 1, 2026-06-15) — content_hash
        # short-circuit. Same (source, content_hash) → this is a replay,
        # return the existing head row without re-running steps 9-11.
        # Distinct content_hash for same source → new version (caller
        # promotes via supersedes; not in this slice).
        existing_head = (
            CortexEntity.objects
            .filter(
                workspace_id=dp.workspace_id,
                source=source_uri,
                content_hash=content_hash,
                superseded_by__isnull=True,
            )
            .first()
        )
        if existing_head is not None:
            logger.info(
                "cortex_dedup_replay_short_circuit",
                extra={
                    "entity_id": str(existing_head.id),
                    "source": source_uri,
                    "content_hash": content_hash[:8],
                },
            )
            return existing_head

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
        # body_md_final passed explicitly: pre-persist the FileField is
        # still unset, so GLiNER cannot read it off the entity (#4 fix).
        context = ExtractContext(
            adapter_metadata=dp.metadata or {},
            body_md=body_md_final,
        )
        candidates = self.extractor.extract(entity=new_entity, context=context)
        # Batch resolve applies the dual-spawn employer link (pushback
        # #11, 2026-06-14): person+org from the same email get an
        # ``employer_org_id`` + ``related`` edge on the person. Custom
        # resolvers without resolve_batch fall back to the old loop.
        if hasattr(self.resolver, "resolve_batch"):
            target_ids = self.resolver.resolve_batch(candidates, scope)
        else:
            target_ids = [self.resolver.resolve(c, scope) for c in candidates]
        entity_refs: list[str] = []
        for target_id in target_ids:
            tid = str(target_id)
            if tid not in entity_refs:
                entity_refs.append(tid)
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
        """Resolve the body markdown for a DeliveryPackage.

        Phase 1 (2026-06-15) — three-tier read path, cheapest first:

        1. ``.extracted.md`` sidecar next to the bronze JSON (cheap
           file read, already markdown).
        2. Re-render via the connector adapter from the bronze JSON
           (one JSON parse + adapter dispatch).
        3. OCR fallback (slowest — only when JSON parse fails).
        """
        from donna.core.integrations.bronze import sidecar_key_for

        # Tier 1 — sidecar.
        sidecar = sidecar_key_for(dp.storage_key)
        try:
            if default_storage.exists(sidecar):
                with default_storage.open(sidecar, "rb") as f:
                    return f.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            logger.warning(
                "cortex_sidecar_read_failed",
                extra={"sidecar": sidecar},
                exc_info=True,
            )

        # Tier 2 — re-render from bronze JSON.
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
            logger.warning(
                "cortex_body_json_unparseable",
                extra={"storage_key": dp.storage_key},
            )
            return ""

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

        # No tier-3 OCR fallback anymore — sidecar covers the common
        # case; if we reach here both sidecar AND adapter rendering
        # failed, return empty so the linter rejects loudly via
        # MISSING_SOURCE_FOOTER instead of silently storing garbage.
        return ""

    def _extensions_from_canonical(self, dp: "DeliveryPackage") -> dict:
        """Return ``dp.canonical_payload['extensions']``.

        Connector adapters emit a typed ``CanonicalEntity`` whose
        extensions are Pydantic-validated at construction. The payload
        was stored on ``DeliveryPackage`` at ingest time; we read it
        verbatim here and the linter slims because all the type / author
        / required-extension checks already passed at the adapter
        boundary.
        """
        payload = dp.canonical_payload or {}
        if not payload:
            raise ValueError(
                f"DeliveryPackage {dp.id} missing canonical_payload — "
                "re-ingest required (pre-Phase-2 row)."
            )
        ext = payload.get("extensions")
        if not isinstance(ext, dict):
            raise ValueError(
                f"DeliveryPackage {dp.id} canonical_payload.extensions "
                "missing or wrong type"
            )
        # Mutable copy — step 5 + step 6 enrich it in-place.
        return dict(ext)

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
