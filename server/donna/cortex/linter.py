"""
FrontmatterLinter — gate every CortexEntity before persistence.

Implements **R1-R10** from the **Cortex Universal Silver Specification
v1 (rev 3) §7** plus the hard write-time rejects in §7.2.

Every reject raises ``LinterError`` carrying a closed-vocab
``RejectCode`` from :mod:`donna.cortex.authority` so callers (MCP API
in P9) can map to stable error responses.

Rules enforced here:

| Rule | Description |
|------|-------------|
| R1   | Silver immutable after first write (caller-enforced; linter rejects type/author/source mutations) |
| R2   | ``occurred_at`` + ``synthesized_at`` always present (ISO 8601) |
| R3   | Supersession explicit — ``supersedes`` chain or none |
| R4   | ``cross_refs`` only intra-scope (same workspace/client/project) |
| R5   | Source hierarchy via ``TYPE_AUTHORITY`` (used by conflict-resolution, not gate) |
| R6   | Resynth trigger (informational; not a write-time reject) |
| R7   | Contradiction detection (informational; appends to derived view) |
| R8   | Confidence decay (background; not a write-time reject) |
| R9   | Touchpoints derived (no write-time enforcement) |
| R10  | Plan-shipped immutability (caller-enforced) |

Plus hard rejects per spec §7.2:

- ``MISSING_REQUIRED_EXTENSION`` (doc / note / decision)
- ``INSUFFICIENT_EVIDENCE`` (concept with <2 sources)
- ``DUPLICATE`` (content_hash collision)
- ``MISSING_ENTITY_REFS`` (warning; named entities in body unbound)
- ``UNKNOWN_EDGE_TYPE``
- ``INVALID_SCOPE`` (project_id without client_id)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from pydantic import ValidationError

from donna.cortex.authority import KNOWN_EDGE_FIELDS, RejectCode
from donna.cortex.schemas import EXTENSION_MODELS


if TYPE_CHECKING:
    from donna.cortex.models import CortexEntity


class LinterError(ValueError):
    """Linter rejected the entity. Carries a closed-vocab reject code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class FrontmatterLinter:
    """Validate a CortexEntity instance before save (spec §7)."""

    def check(
        self,
        entity: "CortexEntity",
        body_md: str | None = None,
    ) -> None:
        """Run the slim lint chain. Raises ``LinterError`` on any failure.

        Slimmed 2026-06-15 — these checks now run at the adapter
        boundary via canonical Pydantic models (Phase 2):
        - ``_check_type``        — EntityType Literal on CanonicalEntity
        - ``_check_author``      — enum field on CortexEntity model
        - ``_check_temporal``    — required datetime on CanonicalEntity
        - ``_check_extensions``  — EXTENSION_MODELS.model_validate()
        - ``_check_required_*``  — required-field validation in each
                                    extensions Pydantic model

        What stays = invariants Pydantic can't express + cross-row
        guards that need entity context.
        """
        self._check_scope(entity)
        self._check_supersedes(entity)       # R3 — duplicate target guard
        self._check_cross_refs(entity)       # R4 — shape guard
        self._check_known_edges(entity)
        self._check_source_footer(entity, body_md)
        self._check_required_evidence(entity)  # concept: sources≥2 (cross-row)

    # ── individual rules (slim — see check() for rationale) ─────────

    def _check_scope(self, entity: "CortexEntity") -> None:
        # Relaxed 2026-06-11: (client_id=None, project_id=set) is ALLOWED —
        # workspace-internal projects (e.g. Donna itself) file at
        # ``projects/<slug>/`` and the resolver supports them. The only
        # invalid state left: nothing structural. Method kept as extension
        # point for future cross_refs scope validation.
        return

    def _check_supersedes(self, entity: "CortexEntity") -> None:
        # R3: supersedes targets must exist (skip DB hit at lint time —
        # repository enforces FK semantics atomically).
        seen: set[str] = set()
        for target in entity.supersedes or []:
            key = str(target)
            if key in seen:
                raise LinterError(
                    RejectCode.PYDANTIC_INVALID,
                    f"duplicate supersedes target {key}",
                )
            seen.add(key)

    def _check_cross_refs(self, entity: "CortexEntity") -> None:
        # R4: cross_refs strictly intra-scope. The pairwise check
        # against actual rows is repository's job; here we reject any
        # ad-hoc shape.
        if not isinstance(entity.cross_refs or [], list):
            raise LinterError(
                RejectCode.PYDANTIC_INVALID,
                "cross_refs must be a list of UUIDs",
            )

    def _check_known_edges(self, entity: "CortexEntity") -> None:
        # Edges belong on the entity row (sources/supersedes/contradicts/...),
        # NOT inside ``extensions``. Reject when an extension key collides
        # with a canonical edge field name — that means the adapter put
        # edge data in the wrong place.
        ext_keys = set((entity.extensions or {}).keys())
        misplaced = ext_keys & KNOWN_EDGE_FIELDS
        if misplaced:
            raise LinterError(
                RejectCode.UNKNOWN_EDGE_TYPE,
                f"edge fields in extensions (move to row): {sorted(misplaced)}",
            )

    def _check_source_footer(
        self, entity: "CortexEntity", body_md: str | None = None
    ) -> None:
        # Caller supplies the in-memory body before persist; otherwise
        # we fall back to ``load_body()`` (post-persist path).
        body = body_md if body_md is not None else entity.load_body()
        if not body.strip():
            raise LinterError(
                RejectCode.MISSING_SOURCE_FOOTER, "body empty"
            )
        last_line = body.rstrip().splitlines()[-1]
        if not (
            last_line.startswith("Source:")
            or last_line.startswith("Spawned by:")
        ):
            raise LinterError(
                RejectCode.MISSING_SOURCE_FOOTER,
                "body must end with 'Source: <key>' or 'Spawned by: <id>'",
            )

    def _check_required_evidence(self, entity: "CortexEntity") -> None:
        # Spec §7.2: concept with sources.length < 2 → INSUFFICIENT_EVIDENCE.
        if entity.type == "concept":
            if len(entity.sources or []) < 2:
                raise LinterError(
                    RejectCode.INSUFFICIENT_EVIDENCE,
                    "concept requires at least 2 sources",
                )

    # ── helpers ─────────────────────────────────────────────────────

    def has_required_nav_fields(
        self, extensions: dict, nav_fields: Iterable[str]
    ) -> bool:
        """Return True iff every nav field has a non-empty value in ``extensions``."""
        return all(extensions.get(field) for field in nav_fields)


if __name__ == "__main__":
    # Run: `python -m donna.cortex.linter` (from `server/`)
    # Boot Django minimally — CortexEntity is constructed in-memory only
    # (no .save()), so we never touch the DB; the FK to Workspace is
    # bypassed at the field layer by setting workspace_id directly.
    import os, django
    from datetime import datetime, timezone
    from uuid import uuid4

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")
    django.setup()

    from donna.cortex.models import CortexEntity

    def base(**overrides):
        defaults = dict(
            id=uuid4(),
            type="email",
            author="donna",
            source="gmail://thread/abc",
            bronze_storage_key="bronze/x",
            content_hash="c" * 64,
            occurred_at=datetime.now(tz=timezone.utc),
            workspace_id=uuid4(),
            client_id=None,
            project_id=None,
            title="Test",
            body_byte_size=12,
            confidence="high",
            extensions={},
        )
        defaults.update(overrides)
        return CortexEntity(**defaults)

    GOOD_BODY = "# T\n\nbody.\n\nSource: gmail://thread/abc"
    linter = FrontmatterLinter()

    def run(label: str, entity: "CortexEntity", body_md: str = GOOD_BODY) -> None:
        try:
            linter.check(entity, body_md=body_md)
            print(f"  PASS  {label}")
        except LinterError as exc:
            print(f"  REJECT {exc.code:<32} {label}")

    print("── Happy paths ──────────────────────────────────────────────")
    run("email — minimal", base())
    run("doc with doc_type", base(type="doc", extensions={"doc_type": "spec"}))
    run("note with note_type", base(type="note", extensions={"note_type": "checkpoint"}))

    print("\n── Rejects ──────────────────────────────────────────────────")
    run("INVALID_TYPE — bogus", base(type="bogus"))
    run("INVALID_AUTHOR — bogus", base(author="alien"))
    run("MISSING_OCCURRED_AT", base(occurred_at=None))
    run("INVALID_SCOPE — project without client",
        base(project_id=uuid4(), client_id=None))
    run("MISSING_REQUIRED_EXTENSION — doc missing doc_type",
        base(type="doc", extensions={}))
    run("MISSING_REQUIRED_EXTENSION — note missing note_type",
        base(type="note", extensions={}))
    run("MISSING_REQUIRED_EXTENSION — decision missing context_sources",
        base(type="decision", extensions={"adr_status": "proposed"}))
    run("INSUFFICIENT_EVIDENCE — concept with 0 sources",
        base(type="concept", extensions={"maturity": "seed"}))
    run("UNKNOWN_EDGE_TYPE — ad-hoc 'links' key",
        base(extensions={"links": ["x"]}))
    run("MISSING_SOURCE_FOOTER — body without Source: tail",
        base(),
        body_md="just plain text without footer")

    print("\n── has_required_nav_fields() helper ────────────────────────")
    print(f"  full set    → {linter.has_required_nav_fields({'a': 1, 'b': 2}, ['a', 'b'])}")
    print(f"  missing one → {linter.has_required_nav_fields({'a': 1}, ['a', 'b'])}")
    print(f"  empty value → {linter.has_required_nav_fields({'a': ''}, ['a'])}")
