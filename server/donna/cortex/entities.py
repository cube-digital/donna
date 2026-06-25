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


# Extractors moved 2026-06-15 to ``donna.core.extractors.entities``.
# Re-exported below for backward compatibility — existing imports
# ``from donna.cortex.entities import ProviderMetadataExtractor`` keep
# working. New code should import from ``donna.core.extractors.entities``.
from donna.core.extractors.entities import (  # noqa: F401
    CompositeExtractor,
    EntityExtractor,
    ExtractContext,
    ExtractedEntity,
    GLiNERExtractor,
    ProviderMetadataExtractor,
)


# ── (Stale local copies removed — see core/extractors/entities/) ────


# ── Resolver ────────────────────────────────────────────────────────


class EntityResolver(Protocol):
    def resolve(
        self, candidate: ExtractedEntity, scope: Scope
    ) -> UUID: ...

    def resolve_batch(
        self, candidates: list[ExtractedEntity], scope: Scope
    ) -> list[UUID]: ...


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

    def resolve_batch(
        self, candidates: list[ExtractedEntity], scope: Scope
    ) -> list[UUID]:
        """Resolve N candidates, then apply employer-link side-effect (#11).

        When a person and an org are both resolved from the same email
        domain (alice@acme.com → Alice + Acme), set the person's
        ``extensions.employer_org_id`` + a ``related`` edge — UNLESS the
        person already has one (human-set values are never overwritten).

        Reverse case (org spawns first, person second) is handled here
        too because we look at the full batch before patching.
        """
        ids: list[UUID] = []
        persons: list[tuple[ExtractedEntity, UUID]] = []
        orgs_by_domain: dict[str, UUID] = {}

        for cand in candidates:
            uid = self.resolve(cand, scope)
            ids.append(uid)
            if cand.type == "person" and cand.email and "@" in cand.email:
                persons.append((cand, uid))
            elif cand.type == "org" and cand.domain:
                orgs_by_domain.setdefault(cand.domain.lower(), uid)

        for cand, person_id in persons:
            domain = cand.email.split("@", 1)[1].lower()
            org_id = orgs_by_domain.get(domain)
            if org_id is not None:
                self._set_employer_if_unset(person_id, org_id)

        return ids

    @staticmethod
    def _set_employer_if_unset(person_id: UUID, org_id: UUID) -> None:
        """Set the person's employer link iff currently empty."""
        try:
            person = CortexEntity.objects.get(id=person_id, type="person")
        except CortexEntity.DoesNotExist:
            return
        ext = dict(person.extensions or {})
        if ext.get("employer_org_id"):
            return  # never overwrite human-set
        ext["employer_org_id"] = str(org_id)
        related = list(person.related or [])
        if str(org_id) not in [str(x) for x in related]:
            related.append(str(org_id))
        person.extensions = ext
        person.related = related
        person.save(update_fields=["extensions", "related", "updated_at"])

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
            "slug": slug,  # folder resolver needs this for people/<slug>.md
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
        own_slug = slugify(candidate.label or candidate.domain or "unknown") or "unknown"
        title = candidate.label or candidate.domain or "Unknown org"
        body = self._body(title, "org")

        # Tier A classifier (2026-06-19, spec 00m) — synchronous, rules
        # only. Returns ``self|vendor|unknown`` reliably; defers
        # client/partner/peer to the nightly batch where direction
        # asymmetry + vocab signals are available.
        from donna.cortex.relationship_classifier import classify_on_spawn
        from donna.workspaces.models import Workspace

        workspace_domain = (
            Workspace.objects
            .filter(id=scope.workspace_id)
            .values_list("primary_domain", flat=True)
            .first()
            or ""
        )
        verdict = classify_on_spawn(
            org_domain=candidate.domain,
            workspace_primary_domain=workspace_domain,
            first_sender_email=getattr(candidate, "first_sender_email", None),
        )

        extensions = {
            "slug": own_slug,
            "legal_name": candidate.label,
            "email_domains": [candidate.domain] if candidate.domain else [],
            "industry": None,
            "relationship": verdict.relationship,
            "relationship_confidence": verdict.confidence,
            "relationship_basis": verdict.basis,
            "relationship_locked": False,
            "relationship_evidence": verdict.evidence,
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
        # Pushback #3 (2026-06-12): _spawn now routes through the linter +
        # the manager. Removes the previous non-atomic ``row.save();
        # row.body.save()`` double-write and stops bypassing the gate.
        from donna.cortex.linter import FrontmatterLinter, LinterError

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

        # Phase 5 vault projection (2026-06-19): spawned entities need
        # ``parent_path`` so the vault renderer files them correctly.
        # The main pipeline computes this in step 6 for the primary
        # entity; spawn-as-side-effect (person/org/concept/project) was
        # being persisted with NULL parent_path. Compute it here using
        # the same folder resolver the pipeline uses.
        from donna.cortex.registry import TemplateRegistry
        from donna.cortex.scope import scope_slugs_for

        try:
            type_spec = TemplateRegistry().get(entity_type)
            spawn_scope = Scope(
                workspace_id=scope.workspace_id,
                client_id=client_id,
                project_id=project_id,
            )
            client_slug, project_slug = scope_slugs_for(spawn_scope)
            parent_path = type_spec.folder_resolver(
                type=entity_type,
                occurred_at=None,
                extensions=extensions,
                client_slug=client_slug,
                project_slug=project_slug,
            )
            extensions = dict(extensions)
            extensions["parent_path"] = parent_path
            if "slug" not in extensions:
                from django.utils.text import slugify as _slugify
                extensions["slug"] = _slugify(title or ident) or "unknown"
        except Exception:  # noqa: BLE001
            # Folder resolution must never block the spawn; degrade
            # to workspace-root if anything goes wrong.
            pass

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

        # Concept exception: requires sources>=2 (INSUFFICIENT_EVIDENCE);
        # single-extraction spawn cannot satisfy that — left to the
        # dedicated batch-synthesis flow. All OTHER lint rules still
        # apply to concept rows; only INSUFFICIENT_EVIDENCE is tolerated.
        from donna.cortex.authority import RejectCode
        try:
            FrontmatterLinter().check(row, body_md=body)
        except LinterError as exc:
            if not (entity_type == "concept" and exc.code == RejectCode.INSUFFICIENT_EVIDENCE):
                raise

        return CortexEntity.objects.save_with_reverse_edges(
            row, body_bytes=body_bytes
        )

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
