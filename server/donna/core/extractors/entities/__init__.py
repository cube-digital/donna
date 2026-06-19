"""Entity extraction primitives — Protocol + Composite + concretes.

Moved out of ``donna.cortex.entities`` in the P0 refactor so the pure
extraction layer (text → candidates) can live in core where any app
that wants entity surfacing from text can import it. The resolver
(DB-bound, spawns curated rows) stays in cortex because it needs
cortex models.
"""
from .base import EntityExtractor, ExtractContext, ExtractedEntity
from .provider import ProviderMetadataExtractor
from .gliner import GLiNERExtractor
from .composite import CompositeExtractor


__all__ = [
    "EntityExtractor",
    "ExtractContext",
    "ExtractedEntity",
    "ProviderMetadataExtractor",
    "GLiNERExtractor",
    "CompositeExtractor",
]
