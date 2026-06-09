"""PersonSpec — curated person entity. Cross-client (spec §6 exception)."""
from __future__ import annotations

from donna.cortex.folders import PersonFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import PersonExtensions


PersonSpec = TypeSpec(
    type="person",
    extensions_model=PersonExtensions,
    fit_model=None,
    template_path="person.j2",
    nav_fields=[],
    folder_resolver=PersonFolderResolver(),
    version="person@v1",
)

register_type(PersonSpec)
