"""
TYPE_AUTHORITY registry + linter reject codes.

Per **Cortex Universal Silver Specification v1 (rev 3) §7.1**.

``TYPE_AUTHORITY`` is a closed numeric registry. When two entities
conflict, the linter uses these weights to decide which "wins" (R5).
Higher = more authoritative.

The sub-discriminated keys (``doc:contract``, ``note:checkpoint``,
etc.) are matched first; bare ``type`` is the fallback.
"""
from __future__ import annotations

from typing import Mapping


TYPE_AUTHORITY: Mapping[str, int] = {
    "decision": 100,
    "doc:contract": 95,
    "doc:signed_document": 95,
    "doc:offer": 80,
    "project": 75,
    "doc:spec": 70,
    "doc:requirements": 70,
    "concept": 65,
    "person": 60,
    "org": 60,
    "meeting": 55,
    "doc:handover": 55,
    "doc:integration_spec": 55,
    "doc:runbook": 55,
    "doc:plan": 50,
    "doc:technical_analysis": 50,
    "email": 50,
    "doc:internal_memo": 45,
    "doc:architecture_note": 45,
    "doc:design_note": 45,
    "ticket": 45,
    "note:checkpoint": 40,
    "note:action_item": 40,
    "note:open_question": 40,
    "note": 35,
    "doc:presentation": 35,
    "chat": 30,
    "doc:other": 25,
    "clip": 20,
    "note:journal": 15,
}


def authority_for(entity_type: str, sub_discriminator: str | None = None) -> int:
    """Look up TYPE_AUTHORITY for ``(type, sub)`` pair.

    Tries ``"<type>:<sub>"`` first, then bare ``type``. Returns 0 if
    neither matches (UNKNOWN type → linter rejects upstream).
    """
    if sub_discriminator:
        key = f"{entity_type}:{sub_discriminator}"
        if key in TYPE_AUTHORITY:
            return TYPE_AUTHORITY[key]
    return TYPE_AUTHORITY.get(entity_type, 0)


# ── Linter reject codes (spec §7.2) ────────────────────────────────


class RejectCode:
    """Closed enum of linter reject codes — every reject MUST carry one."""

    MISSING_REQUIRED_EXTENSION = "MISSING_REQUIRED_EXTENSION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DUPLICATE = "DUPLICATE"
    MISSING_ENTITY_REFS = "MISSING_ENTITY_REFS"  # warning
    IMPLICIT_CONTRADICTION = "IMPLICIT_CONTRADICTION"
    UNKNOWN_EDGE_TYPE = "UNKNOWN_EDGE_TYPE"
    MISSING_SOURCE_FOOTER = "MISSING_SOURCE_FOOTER"
    MISSING_OCCURRED_AT = "MISSING_OCCURRED_AT"
    MISSING_SYNTHESIZED_AT = "MISSING_SYNTHESIZED_AT"
    INVALID_SCOPE = "INVALID_SCOPE"  # client_id null but project_id non-null
    INVALID_CROSS_REF_SCOPE = "INVALID_CROSS_REF_SCOPE"  # R4 violation
    INVALID_TYPE = "INVALID_TYPE"
    INVALID_AUTHOR = "INVALID_AUTHOR"
    PYDANTIC_INVALID = "PYDANTIC_INVALID"


# Canonical edge field names — used by linter to reject ad-hoc edges.
KNOWN_EDGE_FIELDS = {
    "entity_refs",
    "sources",
    "cross_refs",
    "supersedes",
    "parent",
    "related",
    "applied_in",
    "superseded_by",
    "contradicts",
}


if __name__ == "__main__":
    # Run: `python -m donna.cortex.authority` (from `server/`)
    print("── TYPE_AUTHORITY registry (sorted) ─────────────────────────")
    for key, weight in sorted(TYPE_AUTHORITY.items(), key=lambda kv: -kv[1]):
        print(f"  {weight:>3}  {key}")

    print("\n── authority_for() lookup ───────────────────────────────────")
    cases = [
        ("decision", None),
        ("doc", "contract"),
        ("doc", "plan"),
        ("doc", None),         # bare type fallback (0 — bare 'doc' not registered)
        ("note", "checkpoint"),
        ("note", None),
        ("unknown_type", None),
    ]
    for t, sub in cases:
        print(f"  authority_for({t!r}, {sub!r}) = {authority_for(t, sub)}")

    print("\n── Reject codes (closed enum) ───────────────────────────────")
    for name in dir(RejectCode):
        if not name.startswith("_") and name.isupper():
            print(f"  RejectCode.{name} = {getattr(RejectCode, name)!r}")

    print("\n── KNOWN_EDGE_FIELDS ────────────────────────────────────────")
    print(f"  {sorted(KNOWN_EDGE_FIELDS)}")
