"""ClipSpec — Web Clipper / Pocket / Readwise / Raindrop captures."""
from __future__ import annotations

from donna.cortex.folders import FlatFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import ClipExtensions


ClipSpec = TypeSpec(
    type="clip",
    extensions_model=ClipExtensions,
    fit_model=None,
    template_path="clip.j2",
    nav_fields=["url", "why_captured"],
    folder_resolver=FlatFolderResolver(bucket="clips"),
    version="clip@v1",
)

register_type(ClipSpec)
