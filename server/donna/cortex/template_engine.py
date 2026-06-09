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
