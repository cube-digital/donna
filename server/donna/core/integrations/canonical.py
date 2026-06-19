"""Canonical adapter models — Phase 2 (2026-06-15).

One typed Pydantic envelope (``CanonicalEntity``) carrying the four
fields cortex needs from every connector + a per-type ``extensions``
dict that is validated against the matching ``EXTENSION_MODELS`` at
construction time.

Plain English: a connector turns its raw payload into a CanonicalEntity.
That object is THE source of truth for the cortex pipeline — no more
loose-dict ``metadata`` mapping, no more per-type if-chain in
``pipeline._build_extensions``. Pydantic catches missing required
fields at the adapter boundary instead of at the linter.

The linter slims to invariants Pydantic can't express: scope, source
footer, supersession sanity, known-edge fields.

Connector-facing types today (one adapter per (provider, entity)):
    meeting, email, chat, doc, ticket, clip, note

Curated types (spawned by resolver / CRM connector in Phase 7):
    person, org, project, concept, decision

The same ``CanonicalEntity`` envelope serves both — only the
``entity_type`` literal + the ``extensions`` shape change.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from donna.cortex.schemas import EXTENSION_MODELS, EntityType


class CanonicalEntity(BaseModel):
    """Typed envelope every adapter emits.

    Construction validates ``extensions`` against
    ``EXTENSION_MODELS[entity_type]`` — adapters that emit malformed
    payloads fail loudly at the connector boundary instead of silently
    polluting cortex.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: EntityType = Field(
        description="Closed 12-value taxonomy; see cortex.schemas.EntityType.",
    )
    external_id: str = Field(
        description="Provider's stable id (used to compute source URI).",
    )
    title: str = Field(default="Untitled")
    occurred_at: datetime
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-type fields; validated against EXTENSION_MODELS[entity_type].",
    )

    @model_validator(mode="after")
    def _validate_extensions(self) -> "CanonicalEntity":
        # Each entity_type points at a Pydantic model in EXTENSION_MODELS.
        # Run it; missing required nav fields surface as ValidationError
        # at the adapter, not 11 steps deep in the cortex pipeline.
        ext_model = EXTENSION_MODELS.get(self.entity_type)
        if ext_model is None:
            # Should never fire — entity_type is the closed Literal — but
            # guard anyway so the failure is obvious if EntityType drifts.
            raise ValueError(
                f"No extensions model registered for entity_type={self.entity_type!r}"
            )
        ext_model.model_validate(self.extensions or {})
        return self

    def as_payload(self) -> dict[str, Any]:
        """JSON-safe dict for storage on ``DeliveryPackage.canonical_payload``."""
        return self.model_dump(mode="json")
