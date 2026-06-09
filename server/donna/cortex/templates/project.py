"""ProjectSpec — curated project entity (replaces Architecture.md)."""
from __future__ import annotations

from donna.cortex.folders import ProjectFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import ProjectExtensions


ProjectSpec = TypeSpec(
    type="project",
    extensions_model=ProjectExtensions,
    fit_model=None,
    template_path="project.j2",
    nav_fields=["status"],
    folder_resolver=ProjectFolderResolver(),
    version="project@v1",
)

register_type(ProjectSpec)
