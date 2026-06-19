"""GLiNERExtractor — body-text NER via ``urchade/gliner_medium-v2.1``.

Lazy-loaded; the gliner package is optional. Reads body markdown from
``context.body_md`` (not from the entity row — at extract time the
FileField is unset, pre-persist).
"""
from __future__ import annotations

from typing import Iterable

from .base import EntityExtractor, ExtractContext, ExtractedEntity


class GLiNERExtractor(EntityExtractor):
    DEFAULT_MODEL = "urchade/gliner_medium-v2.1"
    DEFAULT_LABELS: tuple[str, ...] = ("person", "org", "project", "concept")
    DEFAULT_THRESHOLD = 0.5

    def __init__(
        self,
        model_name: str | None = None,
        labels: Iterable[str] | None = None,
        threshold: float | None = None,
    ) -> None:
        self._model_name = model_name or self.DEFAULT_MODEL
        self._labels = list(labels or self.DEFAULT_LABELS)
        self._threshold = (
            threshold if threshold is not None else self.DEFAULT_THRESHOLD
        )
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from gliner import GLiNER
            except ImportError as exc:
                raise ImportError(
                    "GLiNERExtractor requires gliner. Install with `uv add gliner`."
                ) from exc
            self._model = GLiNER.from_pretrained(self._model_name)
        return self._model

    def extract(
        self, *, entity, context: ExtractContext
    ) -> list[ExtractedEntity]:
        model = self._load()
        text = context.body_md or ""
        if not text:
            return []
        results = model.predict_entities(
            text, self._labels, threshold=self._threshold
        )
        out: list[ExtractedEntity] = []
        for hit in results:
            label = hit.get("label")
            if label not in ("person", "org", "project", "concept"):
                continue
            out.append(
                ExtractedEntity(
                    type=label,  # type: ignore[arg-type]
                    label=hit.get("text", ""),
                    email=None,
                    domain=None,
                    confidence=float(hit.get("score", 0.0)),
                    span=(int(hit.get("start", 0)), int(hit.get("end", 0))),
                    origin="gliner",
                )
            )
        return out
