"""DecisionSpec — curated ADR.

REQUIRED extensions: ``context_sources`` (R-hard-reject
``MISSING_REQUIRED_EXTENSION``).
"""
from __future__ import annotations

from donna.cortex.folders import DecisionFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import DecisionExtensions


DecisionSpec = TypeSpec(
    type="decision",
    extensions_model=DecisionExtensions,
    fit_model=None,
    template_path="decision.j2",
    nav_fields=["adr_status"],
    folder_resolver=DecisionFolderResolver(),
    version="decision@v1",
)

register_type(DecisionSpec)
