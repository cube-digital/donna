"""OrgSpec — curated org entity.

Exactly one org per workspace carries ``relationship: "self"`` —
the workspace owner. Everything else: client / vendor / partner /
competitor / internal.
"""
from __future__ import annotations

from donna.cortex.folders import OrgFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import OrgExtensions


OrgSpec = TypeSpec(
    type="org",
    extensions_model=OrgExtensions,
    fit_model=None,
    template_path="org.j2",
    nav_fields=["relationship"],
    folder_resolver=OrgFolderResolver(),
    version="org@v1",
)

register_type(OrgSpec)
