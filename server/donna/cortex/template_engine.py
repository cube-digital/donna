"""
TemplateEngine — Jinja2 renderer for CortexEntity body markdown.

Each TypeSpec ships a Jinja template at
``donna/cortex/templates/<type>.j2``. The engine renders it with the
per-type ``extensions`` payload + the raw OCR/adapter markdown body.
Result: the final body_md (frontmatter block + verbatim body + Source
footer).

Two fitters are shipped:

- ``NoOpFitter`` — refuses; used when the TypeSpec declares
  ``fit_model=None`` (Fathom meetings, deterministic Gmail, …).
- ``HaikuFitter`` — LiteLLM-driven; used when nav fields are missing
  and the TypeSpec declares a ``fit_model``.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

from donna.cortex.registry import TypeSpec


TEMPLATE_DIR = Path(__file__).parent / "templates"


class TemplateFitter(Protocol):
    def fit(self, text: str, fit_model: type[BaseModel]) -> BaseModel: ...


class NoOpFitter:
    """Default fitter — refuses to fill, raises if invoked."""

    def fit(self, text: str, fit_model: type[BaseModel]) -> BaseModel:
        raise NotImplementedError(
            "NoOpFitter cannot fill missing nav fields. Wire a real "
            "fitter or ensure adapter.metadata() satisfies nav_fields."
        )


class HaikuFitter:
    """LLM-driven nav-field fill via Anthropic Haiku."""

    DEFAULT_MODEL = "anthropic/claude-3-5-haiku-latest"
    DEFAULT_PROMPT = (
        "Extract structured fields from the document below. "
        "Return ONLY valid JSON matching the provided schema.\n\n"
        "---\n"
    )

    def __init__(self, model: str | None = None) -> None:
        self._model = model or self.DEFAULT_MODEL

    def fit(self, text: str, fit_model: type[BaseModel]) -> BaseModel:
        from donna.core.llm.factory import LLMFactory

        provider = LLMFactory.create(model=self._model)
        response = provider.chat(
            messages=[
                {
                    "role": "user",
                    "content": self.DEFAULT_PROMPT + text[:8000],
                }
            ],
            temperature=0.0,
            response_format=fit_model,
        )
        raw = response.content
        body = raw if isinstance(raw, str) else str(raw)
        return fit_model.model_validate_json(body)


class TemplateEngine:
    """Stateless Jinja renderer used by ``CortexWriter`` step 7."""

    def __init__(self, template_dir: Path | None = None) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        type_spec: TypeSpec,
        *,
        data: BaseModel | dict,
        body_input: str,
        title: str = "",
        occurred_at: datetime | date | str | None = None,
        source_uri: str = "",
        bronze_storage_key: str = "",
    ) -> str:
        """Render ``type_spec.template_path``.

        Args:
            type_spec: Registered TypeSpec for this entity.
            data: Extensions dict (or BaseModel instance) — flows into
                the template as ``data``.
            body_input: Markdown body extracted by the OCR pipeline.
            title: Model-level title.
            occurred_at: Model-level occurred_at.
            source_uri: Provenance URI for the Source footer.
            bronze_storage_key: Bronze blob pointer for the Source footer.
        """
        template = self._env.get_template(type_spec.template_path)
        payload = (
            data.model_dump(mode="json")
            if isinstance(data, BaseModel)
            else dict(data)
        )
        return template.render(
            data=payload,
            body=body_input,
            title=title,
            occurred_at=occurred_at,
            source_uri=source_uri,
            bronze_storage_key=bronze_storage_key,
            type_spec=type_spec,
        )


if __name__ == "__main__":
    # Run: `python -m donna.cortex.template_engine` (from `server/`)
    # Renders the person.j2 template with dummy data. No Django/DB needed.
    from datetime import datetime, timezone

    # Force registration — the templates/<type>.py modules execute
    # register_type() at import time; outside Django app ready() we
    # have to import them explicitly.
    from donna.cortex.templates import person as _person  # noqa: F401
    from donna.cortex.templates import concept as _concept  # noqa: F401
    from donna.cortex.registry import TemplateRegistry

    engine = TemplateEngine()
    registry = TemplateRegistry()

    print("── Registered types ─────────────────────────────────────────")
    print(f"  {registry.types()}")

    print("\n── Render person.j2 ────────────────────────────────────────")
    person_data = {
        "parent_path": "people",
        "slug": "ada-lovelace",
        "full_name": "Ada Lovelace",
        "primary_email": "ada@example.com",
        "role": "engineer",
        "cross_workspace_aliases": ["Ada", "A. Lovelace"],
    }
    rendered = engine.render(
        registry.get("person"),
        data=person_data,
        body_input="Founder, programmer, mathematician.",
        title="Ada Lovelace",
        occurred_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        source_uri="cortex://spawn/demo-1",
        bronze_storage_key="",
    )
    print(rendered)

    print("\n── Render concept.j2 ──────────────────────────────────────")
    concept_data = {
        "parent_path": "concepts",
        "slug": "context-windows",
        "maturity": "growing",
        "aliases": ["context window", "prompt window"],
        "domain": "llm",
    }
    rendered = engine.render(
        registry.get("concept"),
        data=concept_data,
        body_input="Notes on context windows and budgeting.",
        title="Context Windows",
        occurred_at=None,
        source_uri="manual://note/2026-06-11",
        bronze_storage_key="",
    )
    print(rendered)

    print("\n── NoOpFitter raises NotImplementedError ────────────────────")
    try:
        NoOpFitter().fit("text", _person.PersonSpec.extensions_model)
    except NotImplementedError as exc:
        print(f"  OK rejected: {exc}")
