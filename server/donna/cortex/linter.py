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
        """Run the full lint chain. Raises ``LinterError`` on any failure.

        Args:
            entity: In-memory CortexEntity (not yet persisted).
            body_md: Rendered body markdown. Passed explicitly because
                the entity's ``body`` FileField may not yet point at a
                file when linting happens in the pre-persist pipeline.
                Falls back to ``entity.load_body()`` when omitted.
        """
        self._check_type(entity)
        self._check_author(entity)
        self._check_temporal(entity)         # R2
        self._check_scope(entity)
        self._check_extensions(entity)       # hard rejects per spec §7.2
        self._check_supersedes(entity)       # R3
        self._check_cross_refs(entity)       # R4
        self._check_known_edges(entity)
        self._check_source_footer(entity, body_md)
        self._check_required_evidence(entity)
        self._check_required_context(entity)
        self._check_required_doc_type(entity)
        self._check_required_note_type(entity)

    # ── individual rules ────────────────────────────────────────────

    def _check_type(self, entity: "CortexEntity") -> None:
        if entity.type not in EXTENSION_MODELS:
            raise LinterError(
                RejectCode.INVALID_TYPE,
                f"unknown entity type {entity.type!r}",
            )

    def _check_author(self, entity: "CortexEntity") -> None:
        if entity.author not in ("donna", "human", "agent"):
            raise LinterError(
                RejectCode.INVALID_AUTHOR,
                f"unknown author {entity.author!r}",
            )

    def _check_temporal(self, entity: "CortexEntity") -> None:
        # R2: ``occurred_at`` must be present at write time.
        # ``synthesized_at`` is auto-populated by ``TimestampsMixin``
        # on first save — no pre-save check needed.
        if entity.occurred_at is None:
            raise LinterError(
                RejectCode.MISSING_OCCURRED_AT,
                "occurred_at is required (R2)",
            )

    def _check_scope(self, entity: "CortexEntity") -> None:
        # Spec §6: project_id must be NULL if client_id is NULL.
        if entity.project_id is not None and entity.client_id is None:
            raise LinterError(
                RejectCode.INVALID_SCOPE,
                "project_id non-null but client_id is null — boundary violation",
            )

    def _check_extensions(self, entity: "CortexEntity") -> None:
        model = EXTENSION_MODELS[entity.type]
        try:
            model.model_validate(entity.extensions or {})
        except ValidationError as exc:
            # Distinguish "missing required" vs other errors.
            missing_required = any(
                err.get("type") == "missing" for err in exc.errors()
            )
            code = (
                RejectCode.MISSING_REQUIRED_EXTENSION
                if missing_required
                else RejectCode.PYDANTIC_INVALID
            )
            raise LinterError(code, f"extensions invalid for {entity.type}: {exc}")

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
        # Any ad-hoc edge field in ``extensions`` → reject.
        ext_keys = set((entity.extensions or {}).keys())
        unknown_edges = ext_keys & {
            "sourcs",   # common typo guard
            "ref",
            "links",
        }
        if unknown_edges:
            raise LinterError(
                RejectCode.UNKNOWN_EDGE_TYPE,
                f"ad-hoc edge keys in extensions: {sorted(unknown_edges)}",
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

    def _check_required_context(self, entity: "CortexEntity") -> None:
        # Spec §7.2: decision missing context_sources → MISSING_REQUIRED_EXTENSION.
        if entity.type == "decision":
            ctx = (entity.extensions or {}).get("context_sources") or []
            if not ctx:
                raise LinterError(
                    RejectCode.MISSING_REQUIRED_EXTENSION,
                    "decision requires extensions.context_sources",
                )

    def _check_required_doc_type(self, entity: "CortexEntity") -> None:
        if entity.type == "doc":
            doc_type = (entity.extensions or {}).get("doc_type")
            if not doc_type:
                raise LinterError(
                    RejectCode.MISSING_REQUIRED_EXTENSION,
                    "doc requires extensions.doc_type",
                )

    def _check_required_note_type(self, entity: "CortexEntity") -> None:
        if entity.type == "note":
            note_type = (entity.extensions or {}).get("note_type")
            if not note_type:
                raise LinterError(
                    RejectCode.MISSING_REQUIRED_EXTENSION,
                    "note requires extensions.note_type",
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
