"""
TypeSpec + TemplateRegistry — aligned with **Cortex Universal Silver
Specification v1 (rev 3)**.

A ``TypeSpec`` is the four-aligned contract per entity type:

1. Pydantic frontmatter model (extends ``EntityData``).
2. Optional Pydantic fit model (LLM structured output for missing nav).
3. Jinja template (relative to ``donna/cortex/templates/``).
4. Closed-vocabulary Literal taxonomy via the ``type`` field.

Discovered at app ready() by ``CortexConfig`` walking
``donna/cortex/templates/`` for Python modules and importing each so
``register_type(...)`` populates the registry.

Twelve types: meeting, email, chat, doc, ticket, clip, note, person,
org, project, concept, decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from donna.cortex.embeddings import Sampler, fixed_window_sampler
from donna.cortex.schemas import EntityType


@dataclass(frozen=True)
class TypeSpec:
    """Four-aligned contract per entity type.

    P0.14 adds ``embedding_sampler`` — the per-type strategy used when
    feeding the embedder. See the P0.14 plan for the cheat-sheet of
    which sampler each type uses.
    """

    type: EntityType
    extensions_model: type[BaseModel]
    fit_model: type[BaseModel] | None
    template_path: str
    nav_fields: list[str]
    folder_resolver: object  # FolderResolver Protocol
    version: str
    embedding_sampler: Sampler = field(default=fixed_window_sampler)


_REGISTRY: dict[str, TypeSpec] = {}


def register_type(spec: TypeSpec) -> TypeSpec:
    """Register ``spec`` under its type key."""
    existing = _REGISTRY.get(spec.type)
    if existing is not None and existing.version != spec.version:
        raise ValueError(
            f"TypeSpec already registered for {spec.type!r} at "
            f"{existing.version}; refusing to overwrite with {spec.version}."
        )
    _REGISTRY[spec.type] = spec
    return spec


class TemplateRegistry:
    """Read-side view of the registered TypeSpecs."""

    def get(self, type_: str) -> TypeSpec:
        if type_ not in _REGISTRY:
            raise KeyError(f"No TypeSpec registered for {type_!r}")
        return _REGISTRY[type_]

    def types(self) -> list[str]:
        return list(_REGISTRY)

    def all(self) -> dict[str, TypeSpec]:
        return dict(_REGISTRY)


def reset_registry_for_tests() -> None:
    _REGISTRY.clear()
