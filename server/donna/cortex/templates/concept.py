"""ConceptSpec — curated concept (cross-project technical idea/pattern).

Requires ``sources.length >= 2`` (R-hard-reject ``INSUFFICIENT_EVIDENCE``).
"""
from __future__ import annotations

from donna.cortex.folders import ConceptFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import ConceptExtensions


ConceptSpec = TypeSpec(
    type="concept",
    extensions_model=ConceptExtensions,
    fit_model=None,
    template_path="concept.j2",
    nav_fields=["maturity"],
    folder_resolver=ConceptFolderResolver(),
    version="concept@v1",
)

register_type(ConceptSpec)
