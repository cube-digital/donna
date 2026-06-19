"""CompositeExtractor — chain extractors + dedupe."""
from __future__ import annotations

from .base import EntityExtractor, ExtractContext, ExtractedEntity


class CompositeExtractor(EntityExtractor):
    """Run each extractor in order; merge + dedupe by (type, email, domain, label)."""

    def __init__(self, *extractors: EntityExtractor) -> None:
        self._extractors = extractors

    def extract(
        self, *, entity, context: ExtractContext
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
