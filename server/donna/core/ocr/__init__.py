"""Document text extraction with fallback strategies.

Provides an ``OCRFacade`` that tries multiple extraction strategies
in order, falling back on failure or invalid results. Strategy order
is adjusted based on file type for optimal results.

Example::

    from donna.core.ocr import create_ocr

    ocr = create_ocr()
    result = ocr.extract("contract.pdf")
    print(result.text)
    print(result.html)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from donna.core.logging import get_logger
from donna.core.ocr.base import OCRConfig, OCRResult, OCRStrategy

if TYPE_CHECKING:
    from PIL import Image

logger = get_logger(__name__)

# File extensions grouped by best-fit strategy order.
_PDF_EXTENSIONS = frozenset({".pdf"})
_OFFICE_EXTENSIONS = frozenset({".docx", ".doc", ".pptx", ".ppt", ".eml"})


class OCRFacade:
    """Tries extraction strategies in order, falling back on failure or invalid results.

    Strategies are instantiated lazily based on the config. The facade
    reorders them per file type, then iterates and returns the first
    valid result. If all strategies fail validation, the longest
    non-empty result is returned as a best-effort fallback.

    Attributes:
        _config: OCR configuration.
        _strategies: Dict of ``name -> strategy`` for lookup.
    """

    def __init__(self, config: OCRConfig) -> None:
        """Initialise the OCR facade.

        Args:
            config: OCR configuration with ordered strategy list.
        """
        self._config = config
        self._strategies: dict[str, OCRStrategy] = {}
        self._initialize_strategies()

    def _initialize_strategies(self) -> None:
        """Build strategy instances from the config.

        Skips strategies whose dependencies are not installed
        (e.g. torch/easyocr not available in the API image).
        """
        for name in self._config.strategies:
            try:
                self._strategies[name] = self._create_strategy(name)
            except (ImportError, ModuleNotFoundError) as exc:
                logger.info(
                    "ocr.strategy_unavailable",
                    strategy=name,
                    reason=str(exc),
                )
                continue

    def _create_strategy(self, name: str) -> OCRStrategy:
        """Lazily import and instantiate a strategy by name.

        Args:
            name: Strategy identifier.

        Returns:
            An ``OCRStrategy`` instance.

        Raises:
            ValueError: If the strategy name is unknown.
        """
        if name == "pymupdf4llm":
            from donna.core.ocr.pymupdf4llm_ import PyMuPDF4LLMStrategy

            return PyMuPDF4LLMStrategy()
        elif name == "easyocr":
            from donna.core.ocr.easyocr_ import EasyOCRStrategy

            return EasyOCRStrategy(languages=self._config.easyocr_languages)
        elif name == "markitdown":
            from donna.core.ocr.markitdown_ import MarkItDownStrategy

            return MarkItDownStrategy()
        elif name == "llm":
            from donna.core.ocr.llm import LLMStrategy

            return LLMStrategy(
                model=self._config.llm_model,
                prompt=self._config.llm_prompt,
            )
        else:
            raise ValueError(f"Unknown OCR strategy: {name}")

    def _get_strategy_order(self, file_path: Path) -> list[str]:
        """Determine the optimal strategy order based on file type.

        - **PDF:** pymupdf4llm first (fastest, text-native), markitdown,
          easyocr (scans / phone photos), llm (vision fallback).
        - **Office formats** (DOCX, PPTX, EML): markitdown first
          (Microsoft's native converter), then pymupdf4llm, llm.
        - **Images** (PNG, JPG, TIFF, etc.): llm vision first (Claude
          Sonnet — fast, layout-aware markdown output, ~2-4s/image),
          then markitdown, easyocr (offline fallback), pymupdf4llm.
          EasyOCR is kept as fallback for offline / rate-limit cases.

        Only strategies that are configured (present in ``self._strategies``)
        are included.

        Args:
            file_path: Path to the document file.

        Returns:
            Ordered list of strategy names.
        """
        suffix = file_path.suffix.lower()
        configured = set(self._strategies.keys())

        if suffix in _PDF_EXTENSIONS:
            preferred = ["pymupdf4llm", "markitdown", "easyocr", "llm"]
        elif suffix in _OFFICE_EXTENSIONS:
            preferred = ["markitdown", "pymupdf4llm", "llm"]
        else:
            preferred = ["llm", "markitdown", "easyocr", "pymupdf4llm"]

        # Filter to only configured strategies, preserving preferred order.
        # Append any configured strategies not in the preferred list at the end.
        ordered = [s for s in preferred if s in configured]
        for s in configured:
            if s not in ordered:
                ordered.append(s)

        return ordered

    def extract(self, file_path: Path | str) -> OCRResult:
        """Extract text from a document, trying strategies in optimal order.

        Strategy order is determined by file type. Falls back to the
        next strategy when the current one raises an exception or
        returns invalid text. If all strategies fail validation but
        at least one returned non-empty text, the longest result is
        returned as a best-effort fallback.

        Args:
            file_path: Path to the document file.

        Returns:
            ``OCRResult`` from the first successful strategy, or the
            best available result if all fail validation.

        Raises:
            FileNotFoundError: If the file does not exist.
            RuntimeError: If all strategies fail with no usable output.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File {file_path} does not exist")

        strategy_order = self._get_strategy_order(file_path)
        logger.info(
            "ocr.extract",
            file=str(file_path),
            strategy_order=strategy_order,
        )

        errors: list[tuple[str, Exception]] = []
        best_result: OCRResult | None = None

        for name in strategy_order:
            strategy = self._strategies[name]
            try:
                logger.info("ocr.attempt", strategy=name, file=str(file_path))
                result = strategy.extract(file_path)

                if result.is_valid:
                    logger.info("ocr.success", strategy=name, chars=len(result.text))
                    return result

                # Not valid but has text — keep as best-effort candidate
                if not result.is_empty:
                    logger.warning(
                        "ocr.invalid_result",
                        strategy=name,
                        chars=len(result.text),
                    )
                    if best_result is None or len(result.text) > len(best_result.text):
                        best_result = result
                else:
                    logger.warning(
                        "ocr.empty_result", strategy=name, file=str(file_path)
                    )

            except Exception as exc:
                logger.warning("ocr.failed", strategy=name, error=str(exc))
                errors.append((name, exc))
                continue

        # Best-effort: return longest non-empty result even if validation failed
        if best_result is not None:
            logger.warning(
                "ocr.best_effort",
                provider=best_result.provider,
                chars=len(best_result.text),
            )
            return best_result

        error_summary = "; ".join(f"{n}: {e}" for n, e in errors)
        raise RuntimeError(
            f"All OCR strategies failed for {file_path}: {error_summary}"
        )

    def extract_from_bytes(self, data: bytes, suffix: str) -> OCRResult:
        """Extract text from raw bytes.

        Writes bytes to a temporary file and delegates to ``extract()``.

        Args:
            data: Raw file content.
            suffix: File extension including dot (e.g. ``".pdf"``).

        Returns:
            ``OCRResult`` from the first successful strategy.
        """
        tmp_path = Path(tempfile.mkstemp(suffix=suffix)[1])
        try:
            tmp_path.write_bytes(data)
            return self.extract(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def extract_from_image(self, image: Image.Image) -> OCRResult:
        """Extract text from a PIL Image.

        Saves the image as a temporary PNG and delegates to ``extract()``.

        Args:
            image: PIL Image instance.

        Returns:
            ``OCRResult`` from the first successful strategy.
        """
        tmp_path = Path(tempfile.mkstemp(suffix=".png")[1])
        try:
            image.save(tmp_path, format="PNG")
            return self.extract(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)


def create_ocr(config: OCRConfig | None = None) -> OCRFacade:
    """Factory that returns an OCR facade.

    Args:
        config: Optional OCR configuration. Defaults to ``OCRConfig()``
            which uses all four strategies in order.

    Returns:
        Configured ``OCRFacade`` instance.
    """
    if config is None:
        config = OCRConfig()
    return OCRFacade(config)


__all__ = [
    "OCRConfig",
    "OCRFacade",
    "OCRResult",
    "OCRStrategy",
    "create_ocr",
]
