"""
BaseAdapter — converts raw provider data to multiple output formats.

Same source → text (for storage/agent memory), markdown (for Documents),
json (for indexes), metadata (for the DeliveryPackage row).

Concrete adapters live in `donna/integrations/connectors/<vendor>/<product>/adapter.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


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
        """Provider-specific normalized metadata. Default empty dict."""
        return {}
