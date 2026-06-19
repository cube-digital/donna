"""Entity extractor base types — Protocol + dataclasses.

Pure-Python — no Django/ORM deps so this module can be imported from
anywhere without dragging in app models.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ExtractContext:
    """Out-of-band context for extractor calls."""

    adapter_metadata: dict
    # Pre-rendered body markdown — required for body-text extractors
    # (GLiNER) because the entity FileField isn't attached yet at
    # extract time (pipeline step 9 runs pre-persist).
    body_md: str = ""


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


class EntityExtractor(Protocol):
    """Surface candidate entities from some source (metadata, body, etc.)."""

    def extract(
        self, *, entity, context: ExtractContext
    ) -> list[ExtractedEntity]: ...
