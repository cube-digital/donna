"""
BaseAdapter + BaseEntityAdapter — connector → cortex contract.

Two shapes co-exist after the 2026-06-15 Phase 2 refactor:

- ``BaseAdapter`` (legacy) — multi-format renderer:
  text / markdown / json / metadata. Still required for the bronze
  storage write (``adapter.to_json()`` lands in default_storage).

- ``BaseEntityAdapter`` (canonical) — emits ONE
  ``CanonicalEntity`` via ``to_canonical()``. The cortex pipeline
  reads ``DeliveryPackage.canonical_payload`` instead of mapping
  ``metadata`` through the old ``_build_extensions`` if-chain.

Concrete adapters subclass BOTH (or wrap one with the other) so
bronze + cortex paths both work without a hard cutover. New
connectors should subclass BaseEntityAdapter directly and inherit
sensible defaults for the legacy methods.

Concrete adapters live in
``donna/integrations/connectors/<vendor>/<product>/adapter.py``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar, Generic, TypeVar

from donna.core.integrations.canonical import CanonicalEntity


class BaseAdapter(ABC):
    """
    Adapter contract: ingestable item → multiple output formats.

    Required: external_id, title, occurred_at, to_json
    Optional (default empty): to_text, to_markdown, metadata
    """

    def __init__(self, raw: dict):
        self.raw = raw

    # ── Required ────────────────────────────────────────────────────────────
    @abstractmethod
    def external_id(self) -> str:
        """Provider's stable identifier (meeting ID, email ID, issue ID, …)."""
        ...

    @abstractmethod
    def title(self) -> str:
        """Human-readable title for the item."""
        ...

    @abstractmethod
    def occurred_at(self) -> datetime:
        """When the source event happened (meeting date, email sent, etc.)."""
        ...

    @abstractmethod
    def to_json(self) -> dict:
        """Structured representation suitable for storage / search index."""
        ...

    # ── Optional (override when meaningful) ─────────────────────────────────
    def to_text(self) -> str:
        """Plain text representation. Default empty — override when meaningful."""
        return ""

    def to_markdown(self) -> str:
        """Markdown representation. Default empty — override when meaningful."""
        return ""

    def metadata(self) -> dict:
        """Provider-specific normalized metadata. Default empty dict.

        Kept for legacy callers; the cortex pipeline now reads
        ``CanonicalEntity`` via ``to_canonical()`` instead.
        """
        return {}


T = TypeVar("T", bound=CanonicalEntity)


class BaseEntityAdapter(BaseAdapter, Generic[T]):
    """Adapter that ALSO emits a typed ``CanonicalEntity``.

    Subclasses set ``canonical_type`` (entity_type literal) and
    implement ``_extensions()`` returning the per-type extensions dict.
    Default ``to_canonical()`` assembles everything; override only when
    a connector needs custom assembly.
    """

    canonical_type: ClassVar[str] = ""

    def _extensions(self) -> dict:
        """Return the typed extensions dict for this entity type.

        Subclasses override. Default falls back to ``metadata()`` so
        adapters that haven't migrated still produce a CanonicalEntity
        — Pydantic will reject if the legacy metadata doesn't fit the
        type's EXTENSION_MODELS schema, flagging the connector to fix.
        """
        return self.metadata()

    def to_canonical(self) -> CanonicalEntity:
        if not self.canonical_type:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set ``canonical_type`` "
                "ClassVar (e.g. 'meeting', 'email', 'doc')."
            )
        return CanonicalEntity(
            entity_type=self.canonical_type,  # type: ignore[arg-type]
            external_id=self.external_id(),
            title=self.title(),
            occurred_at=self.occurred_at(),
            extensions=self._extensions(),
        )
