"""OCR base types.

Provides the Protocol, result dataclass, and configuration for
document text extraction strategies.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# Default vision model for the LLM strategy. Claude Sonnet handles
# Romanian legal documents and complex layouts (tables, numbered
# clauses) materially better than GPT-4o-mini. Override per-deployment
# via ``OCR_LLM_MODEL`` env var without touching the Python defaults.
_DEFAULT_LLM_MODEL = os.environ.get(
    "OCR_LLM_MODEL", "anthropic/claude-sonnet-4-6"
)

# LLM refusal / unambiguous failure messages. These phrases mean the
# extraction itself failed; checked at the start of the response.
# Real documents virtually never open with these.
_LLM_REFUSAL_INDICATORS = frozenset(
    {
        "i'm unable to assist",
        "i cannot assist",
        "i'm not able to",
        "i can't assist",
        "i cannot process",
        "no text found",
    }
)

# Generic API/auth error phrases. These are common in legitimate
# technical documents (API manuals, audit reports, RCAs, security
# policies, dev guides) so they're only treated as failures when the
# response itself is short — i.e. the text *is* the error message
# rather than a document that happens to mention errors.
_API_ERROR_INDICATORS = frozenset(
    {
        "api key",
        "authentication error",
        "unauthorized",
        "rate limit",
        "quota exceeded",
        "invalid api",
        "access denied",
        "permission denied",
        "connection refused",
        "timeout error",
    }
)

# Below this length, generic API error indicators are treated as fatal.
_API_ERROR_TEXT_BUDGET = 150

# Minimum characters for extracted text to be considered valid.
_MIN_TEXT_LENGTH = 20


@dataclass(frozen=True)
class OCRResult:
    """Unified result from any document text extraction strategy.

    Attributes:
        text: Extracted text in markdown format.
        html: Optional HTML representation of the extracted text.
        provider: Name of the strategy that produced this result.
        page_count: Number of pages in the source document.
        title: Document title if detected.
        metadata: Provider-specific metadata (tables, TOC, etc.).
        duration_seconds: Wall-clock extraction time in seconds.
    """

    text: str
    html: str | None = None
    provider: str = ""
    page_count: int | None = None
    title: str | None = None
    metadata: dict = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def is_empty(self) -> bool:
        """Check if extraction produced no meaningful text.

        Returns:
            True if text is empty or whitespace-only.
        """
        return not self.text or not self.text.strip()

    @property
    def is_valid(self) -> bool:
        """Check if extraction produced valid, usable text.

        Goes beyond ``is_empty`` — also rejects text that is too short,
        looks like an LLM refusal, or appears to be an API/auth error
        rather than document content.

        Heuristic:
          * LLM refusal phrases (``"I cannot assist"``, …) anywhere in
            the first 300 chars → reject.
          * Generic API/auth error phrases (``"unauthorized"``,
            ``"permission denied"``, …) → reject only when the whole
            text is short (≤ ``_API_ERROR_TEXT_BUDGET``). Real documents
            mention these phrases legitimately (API manuals, audit
            reports, security policies); a short response that contains
            them is almost certainly the error itself.
          * Python traceback / ``error:`` near the start → reject.

        Returns:
            True if the text appears to be genuine document content.
        """
        if self.is_empty:
            return False

        stripped = self.text.strip()

        if len(stripped) < _MIN_TEXT_LENGTH:
            return False

        lower = stripped.lower()
        head = lower[:300]

        for indicator in _LLM_REFUSAL_INDICATORS:
            if indicator in head:
                return False

        if len(stripped) <= _API_ERROR_TEXT_BUDGET:
            for indicator in _API_ERROR_INDICATORS:
                if indicator in lower:
                    return False

        return "traceback" not in lower[:500] and "error:" not in lower[:300]


@runtime_checkable
class OCRStrategy(Protocol):
    """Interface for document text extraction strategies.

    Each implementation wraps a single extraction library and
    returns a unified ``OCRResult``. The facade tries strategies
    in order and falls back on failure or empty results.
    """

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text content from a document.

        Args:
            file_path: Path to the document file.

        Returns:
            ``OCRResult`` with extracted text and metadata.

        Raises:
            ValueError: If the file format is not supported.
            FileNotFoundError: If the file does not exist.
        """
        ...


@dataclass(frozen=True)
class OCRConfig:
    """Configuration for the OCR facade.

    Attributes:
        strategies: Ordered tuple of strategy names to try.
        llm_model: Model name for the LLM vision strategy.
        llm_prompt: Custom prompt for LLM extraction. None uses default.
        easyocr_languages: Languages for the EasyOCR strategy. Defaults
            to Romanian + English to cover Docupal's primary corpus.
    """

    strategies: tuple[str, ...] = (
        "pymupdf4llm",
        "markitdown",
        "easyocr",
        "llm",
    )
    llm_model: str = _DEFAULT_LLM_MODEL
    llm_prompt: str | None = None
    easyocr_languages: tuple[str, ...] = ("ro", "en")
