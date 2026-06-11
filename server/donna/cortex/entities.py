"""
Entity extraction + resolution — spec-aligned (rev 3).

Two-stage Subsystem 3 pipeline:

1. **Extractor** → surface candidates from provider metadata + optional
   GLiNER body NER. ``CompositeExtractor`` chains both and dedupes.
2. **Resolver** → match each candidate to an existing curated row
   (``person`` / ``org`` / ``project`` / ``concept``) or spawn a new
   one. Returns the target UUID for the writer to drop into
   ``entity_refs[]``.

Spawned rows ship with full provenance:

- ``author``: ``"donna"`` (resolver runs in the connector pipeline)
- ``source``: ``cortex://spawn/<short-id>`` URI
- ``body_md`` ends with ``Spawned by: cortex-resolver`` (linter footer)
- ``extensions`` per type (e.g. ``OrgExtensions.relationship``)
"""
from __future__ import annotations

# ── __main__ bootstrap ──────────────────────────────────────────────
# When invoked as `python -m donna.cortex.entities`, `__name__` is
# "__main__" from line one. Bootstrap Django BEFORE the ORM-bound
# imports below. We do NOT migrate or hit the DB — Cortex models
# require pgvector; the demo exercises only the pure-Python extractor
# path. Resolver paths are documented but not executed.
if __name__ == "__main__":
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")
    import django
    django.setup()

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal, Protocol
from uuid import UUID, uuid4

from django.utils.text import slugify

from donna.cortex.clustering import Scope
from donna.cortex.models import CortexEntity


_PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "live.com",
    "msn.com",
    "aol.com",
}


@dataclass(frozen=True)
class ExtractContext:
    """Out-of-band context for extractor calls."""

    adapter_metadata: dict


@dataclass(frozen=True)
class ExtractedEntity:
    """A single candidate surfaced by an Extractor."""

    type: Literal["person", "org", "project", "concept"]
    label: str
    email: str | None
    domain: str | None
    confidence: float
    span: tuple[int, int] | None
    origin: Literal["provider", "gliner", "haiku_hint"]


# ── Extractors ──────────────────────────────────────────────────────


class EntityExtractor(Protocol):
    def extract(
        self, *, entity: CortexEntity, context: ExtractContext
    ) -> list[ExtractedEntity]: ...


class ProviderMetadataExtractor:
    """Deterministic extraction from ``adapter.metadata()``."""

    def extract(
        self, *, entity: CortexEntity, context: ExtractContext
    ) -> list[ExtractedEntity]:
        meta = context.adapter_metadata or {}
        out: list[ExtractedEntity] = []

        for source in ("host", "sender", "owner"):
            obj = meta.get(source)
            if isinstance(obj, dict) and obj.get("email"):
                out.append(self._person(obj))

        for source in ("participants", "recipients", "to", "cc", "attendees"):
            for item in meta.get(source) or []:
                if isinstance(item, dict) and item.get("email"):
                    out.append(self._person(item))
                elif isinstance(item, str) and "@" in item:
                    out.append(self._person({"email": item, "name": item}))

        seen_domains: set[str] = set()
        for cand in list(out):
            if cand.email and "@" in cand.email:
                domain = cand.email.split("@", 1)[1].lower()
                if domain in _PUBLIC_EMAIL_DOMAINS:
                    continue
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)
                out.append(
                    ExtractedEntity(
                        type="org",
                        label=domain.split(".")[0].capitalize(),
                        email=None,
                        domain=domain,
                        confidence=0.9,
                        span=None,
                        origin="provider",
                    )
                )

        return out

    def _person(self, obj: dict) -> ExtractedEntity:
        return ExtractedEntity(
            type="person",
            label=obj.get("name") or obj.get("email"),
            email=(obj.get("email") or "").lower() or None,
            domain=None,
            confidence=1.0,
            span=None,
            origin="provider",
        )


class GLiNERExtractor:
    """Body-text NER via ``urchade/gliner_medium-v2.1`` (lazy-loaded)."""

    DEFAULT_MODEL = "urchade/gliner_medium-v2.1"
    DEFAULT_LABELS: tuple[str, ...] = ("person", "org", "project", "concept")
    DEFAULT_THRESHOLD = 0.5

    def __init__(
        self,
        model_name: str | None = None,
        labels: Iterable[str] | None = None,
        threshold: float | None = None,
    ) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._labels = list(labels or self.DEFAULT_LABELS)
        self._threshold = (
            threshold if threshold is not None else self.DEFAULT_THRESHOLD
        )
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from gliner import GLiNER
            except ImportError as exc:
                raise ImportError(
                    "GLiNERExtractor requires gliner. "
                    "Install with `uv add gliner`."
                ) from exc
            self._model = GLiNER.from_pretrained(self._model_name)
        return self._model

    def extract(
        self, *, entity: CortexEntity, context: ExtractContext
    ) -> list[ExtractedEntity]:
        model = self._load()
        text = entity.body_md or ""
        results = model.predict_entities(
            text, self._labels, threshold=self._threshold
        )
        out: list[ExtractedEntity] = []
        for hit in results:
            label = hit.get("label")
            if label not in ("person", "org", "project", "concept"):
                continue
            out.append(
                ExtractedEntity(
                    type=label,  # type: ignore[arg-type]
                    label=hit.get("text", ""),
                    email=None,
                    domain=None,
                    confidence=float(hit.get("score", 0.0)),
                    span=(int(hit.get("start", 0)), int(hit.get("end", 0))),
                    origin="gliner",
                )
            )
        return out


class CompositeExtractor:
    """Chain of Responsibility — run each; merge + dedupe."""

    def __init__(self, *extractors: EntityExtractor) -> None:
        self._extractors = extractors

    def extract(
        self, *, entity: CortexEntity, context: ExtractContext
    ) -> list[ExtractedEntity]:
        seen: set[tuple[str, str, str, str]] = set()
        merged: list[ExtractedEntity] = []
        for ext in self._extractors:
            for cand in ext.extract(entity=entity, context=context):
                key = (
                    cand.type,
                    (cand.email or "").lower(),
                    (cand.domain or "").lower(),
                    (cand.label or "").lower(),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(cand)
        return merged


# ── Resolver ────────────────────────────────────────────────────────


class EntityResolver(Protocol):
    def resolve(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID: ...


class DeterministicResolver:
    """Match candidate → existing curated row, or spawn a new one.

    Resolution rules:

    - person: ``extensions.primary_email`` exact match (lowercased), or
      label vs ``extensions.cross_workspace_aliases[]``.
    - org: canonical domain exact match against ``extensions.email_domains[]``,
      or label vs aliases.
    - project / concept: label vs aliases only.

    Spawned rows are workspace-scoped curated entities. People +
    concepts spawn at workspace root regardless of scope (spec §6
    exceptions). Orgs spawn at workspace root for ``relationship=self``,
    otherwise under the client they belong to.
    """

    def resolve(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        if candidate.type == "person":
            return self._resolve_person(candidate, scope)
        if candidate.type == "org":
            return self._resolve_org(candidate, scope)
        if candidate.type == "project":
            return self._resolve_project(candidate, scope)
        if candidate.type == "concept":
            return self._resolve_concept(candidate, scope)
        raise ValueError(f"Unknown candidate.type={candidate.type!r}")

    # ── person ─────────────────────────────────────────────────────

    def _resolve_person(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        ws = scope.workspace_id
        if candidate.email:
            existing = CortexEntity.objects.filter(
                workspace_id=ws,
                type="person",
                extensions__primary_email=candidate.email,
            ).first()
            if existing:
                return existing.id

        if candidate.label:
            existing = CortexEntity.objects.filter(
                workspace_id=ws,
                type="person",
                extensions__cross_workspace_aliases__contains=[candidate.label],
            ).first()
            if existing:
                return existing.id

        return self._spawn_person(candidate, scope)

    def _spawn_person(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        slug = slugify(candidate.label or candidate.email or "unknown") or "unknown"
        title = candidate.label or candidate.email or "Unknown person"
        body = self._body(title, "person")
        extensions = {
            "full_name": candidate.label,
            "primary_email": candidate.email,
            "role": None,
            "employer_org_id": None,
            "cross_workspace_aliases": [candidate.label] if candidate.label else [],
        }
        return self._spawn(
            entity_type="person",
            scope=scope,
            title=title,
            body=body,
            extensions=extensions,
            ident=candidate.email or slug,
            client_id=None,  # cross-client per spec §6
            project_id=None,
        ).id

    # ── org ────────────────────────────────────────────────────────

    def _resolve_org(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        ws = scope.workspace_id
        if candidate.domain:
            existing = CortexEntity.objects.filter(
                workspace_id=ws,
                type="org",
                extensions__email_domains__contains=[candidate.domain],
            ).first()
            if existing:
                return existing.id

        if candidate.label:
            existing = CortexEntity.objects.filter(
                workspace_id=ws,
                type="org",
                extensions__cross_workspace_aliases__contains=[candidate.label],
            ).first()
            if existing:
                return existing.id

        return self._spawn_org(candidate, scope)

    def _spawn_org(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        slug = slugify(candidate.label or candidate.domain or "unknown") or "unknown"
        title = candidate.label or candidate.domain or "Unknown org"
        body = self._body(title, "org")
        extensions = {
            "legal_name": candidate.label,
            "email_domains": [candidate.domain] if candidate.domain else [],
            "industry": None,
            "relationship": "client",  # safest default; spec §3.2
        }
        return self._spawn(
            entity_type="org",
            scope=scope,
            title=title,
            body=body,
            extensions=extensions,
            ident=candidate.domain or slug,
            client_id=None,
            project_id=None,
        ).id

    # ── project ────────────────────────────────────────────────────

    def _resolve_project(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        if candidate.label:
            existing = CortexEntity.objects.filter(
                workspace_id=scope.workspace_id,
                type="project",
                extensions__cross_workspace_aliases__contains=[candidate.label],
            ).first()
            if existing:
                return existing.id
        return self._spawn_project(candidate, scope)

    def _spawn_project(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        slug = slugify(candidate.label or "unknown") or "unknown"
        title = candidate.label or "Unknown project"
        body = self._body(title, "project")
        extensions = {
            "status": "active",
            "target_ship_date": None,
            "repo_url": None,
            "deployed_url": None,
            "stack": [],
            "cross_workspace_aliases": [candidate.label] if candidate.label else [],
        }
        return self._spawn(
            entity_type="project",
            scope=scope,
            title=title,
            body=body,
            extensions=extensions,
            ident=slug,
            client_id=scope.client_id,
            project_id=None,  # project row carries no project_id self-link
        ).id

    # ── concept ────────────────────────────────────────────────────

    def _resolve_concept(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        if candidate.label:
            existing = CortexEntity.objects.filter(
                workspace_id=scope.workspace_id,
                type="concept",
                extensions__aliases__contains=[candidate.label],
            ).first()
            if existing:
                return existing.id
        return self._spawn_concept(candidate, scope)

    def _spawn_concept(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID:
        slug = slugify(candidate.label or "unknown") or "unknown"
        title = candidate.label or "Unknown concept"
        body = self._body(title, "concept")
        extensions = {
            "aliases": [candidate.label] if candidate.label else [],
            "domain": None,
            "maturity": "seed",
        }
        # NOTE: concept has INSUFFICIENT_EVIDENCE if sources<2. The
        # extractor pipeline cannot give a concept two sources at spawn
        # time, so concept-spawn is left to a separate flow (human or
        # batch synthesis). We still allow the row but flag it for the
        # human-review pipeline by keeping sources empty.
        return self._spawn(
            entity_type="concept",
            scope=scope,
            title=title,
            body=body,
            extensions=extensions,
            ident=slug,
            client_id=None,
            project_id=None,
        ).id

    # ── shared spawn ────────────────────────────────────────────────

    def _spawn(
        self,
        *,
        entity_type: str,
        scope: Scope,
        title: str,
        body: str,
        extensions: dict,
        ident: str,
        client_id: UUID | None,
        project_id: UUID | None,
    ) -> CortexEntity:
        from django.core.files.base import ContentFile

        spawn_id = uuid4()
        source_uri = f"cortex://spawn/{spawn_id}"
        content_hash = hashlib.sha256(
            f"{entity_type}:{ident}".encode()
        ).hexdigest()

        # Idempotent fast-path: existing row → return as-is.
        existing = CortexEntity.objects.filter(
            workspace_id=scope.workspace_id,
            content_hash=content_hash,
        ).first()
        if existing is not None:
            return existing

        body_bytes = body.encode("utf-8")
        row = CortexEntity(
            id=spawn_id,
            workspace_id=scope.workspace_id,
            type=entity_type,
            author="donna",
            source=source_uri,
            bronze_storage_key="",
            content_hash=content_hash,
            occurred_at=datetime.now(tz=timezone.utc),
            client_id=client_id,
            project_id=project_id,
            title=title,
            body_byte_size=len(body_bytes),
            confidence="medium",
            last_synthesized=datetime.now(tz=timezone.utc).date(),
            extensions=extensions,
        )
        row.save()
        row.body.save(
            name=f"{row.id}.md",
            content=ContentFile(body_bytes),
            save=True,
        )
        return row

    def _body(self, title: str, type_label: str) -> str:
        return (
            f"---\n"
            f"type: {type_label}\n"
            f"title: {title}\n"
            f"---\n\n"
            f"# {title}\n\n"
            f"_Spawned by the Cortex resolver._\n\n"
            f"Spawned by: cortex-resolver"
        )


if __name__ == "__main__":
    # Run: `python -m donna.cortex.entities` (from `server/`)
    # Django was bootstrapped at the top of the module.

    print("── ExtractedEntity dataclass shape ──────────────────────────")
    cand = ExtractedEntity(
        type="person",
        label="Ada Lovelace",
        email="ada@acme.com",
        domain=None,
        confidence=1.0,
        span=None,
        origin="provider",
    )
    print(f"  {cand}")

    print("\n── ProviderMetadataExtractor (pure-Python, no DB) ───────────")
    meta = {
        "host":        {"name": "Ada Lovelace", "email": "ada@acme.com"},
        "attendees":  [{"name": "Bob",          "email": "bob@acme.com"},
                       {"name": "Eve",          "email": "eve@gmail.com"}],  # public domain
        "recipients": ["carol@beta.io"],
    }
    extracted = ProviderMetadataExtractor().extract(
        entity=None,  # not dereferenced by this extractor
        context=ExtractContext(adapter_metadata=meta),
    )
    for e in extracted:
        print(f"  {e.type:<7} label={e.label!r:<25} email={e.email!r:<22} domain={e.domain!r}")

    print("\n── Public domains (gmail.com, …) → NO org candidate spawned ─")
    print(f"  org candidates: {[(e.label, e.domain) for e in extracted if e.type == 'org']}")
    print(f"  (eve@gmail.com is in _PUBLIC_EMAIL_DOMAINS → no org for gmail.com)")

    print("\n── CompositeExtractor dedupes across chain ──────────────────")
    composite = CompositeExtractor(
        ProviderMetadataExtractor(),
        ProviderMetadataExtractor(),  # duplicate intentionally
    )
    merged = composite.extract(
        entity=None,
        context=ExtractContext(adapter_metadata=meta),
    )
    print(f"  count after dedup: {len(merged)}  (vs raw {2 * len(extracted)})")

    print("\n── DeterministicResolver — DB-bound; shape only ─────────────")
    resolver = DeterministicResolver()
    print(f"  resolver = {resolver.__class__.__name__}()")
    print( "  Resolution rules per type:")
    print( "    person  → match extensions.primary_email; else label alias; else spawn")
    print( "    org     → match extensions.email_domains[]; else label alias; else spawn")
    print( "    project → label alias only; else spawn (under client_id if set)")
    print( "    concept → label alias only; else spawn at workspace root")
    print( "  Real resolve() calls require Postgres + pgvector — exercise via the")
    print( "  Django shell:  `python -m django shell` then call resolver.resolve(...).")
