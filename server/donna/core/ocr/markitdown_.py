"""MarkItDown extraction strategy (Microsoft).

Converts documents to markdown using Microsoft's MarkItDown library.
Supports the broadest range of file formats of any strategy, including
PDF, Office documents, images, audio, HTML, and archives.

HTML output is produced by converting the markdown via
``markdown_to_html()`` from ``donna.core.ocr.utils``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, ClassVar

from django.conf import settings
from markitdown import MarkItDown

from donna.core.logging import get_logger
from donna.core.ocr.base import OCRResult
from donna.core.ocr.utils import markdown_to_html

logger = get_logger(__name__)


class MarkItDownStrategy:
    """Document-to-markdown extraction using Microsoft MarkItDown.

    Broadest format support of all strategies. Produces markdown only —
    HTML is generated via ``markdown_to_html()``. Metadata extraction
    is minimal (title only, no page count or tables).

    When an API key is configured via ``settings.MARKITDOWN_API_KEY``,
    MarkItDown uses it for LLM-powered image description and audio
    transcription on those file types.

    Attributes:
        SUPPORTED_FORMATS: List of file extensions this strategy handles.
        markitdown: Configured ``MarkItDown`` instance.
    """

    SUPPORTED_FORMATS: ClassVar[list[str]] = [
        ".pdf",
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
        ".html",
        ".htm",
        ".csv",
        ".json",
        ".xml",
        ".zip",
        ".epub",
        ".wav",
        ".mp3",
        ".m4a",
        ".flac",
        ".aac",
        ".ogg",
        ".eml",
    ]

    def __init__(self, enable_plugins: bool = False, **kwargs: Any) -> None:
        """Initialise the MarkItDown converter.

        Args:
            enable_plugins: Whether to enable MarkItDown plugins for
                extended format support.
            **kwargs: Additional keyword arguments passed to
                ``MarkItDown()``.
        """
        api_key = getattr(settings, "MARKITDOWN_API_KEY", None)
        md_kwargs: dict[str, Any] = dict(enable_plugins=enable_plugins, **kwargs)
        if api_key:
            md_kwargs["api_key"] = api_key
        self.markitdown = MarkItDown(**md_kwargs)

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text from a document using MarkItDown.

        Converts the file to markdown, then generates HTML via
        ``markdown_to_html()``. Only ``title`` metadata is available
        from MarkItDown's result — ``page_count`` is not supported.

        Args:
            file_path: Path to the document file.

        Returns:
            ``OCRResult`` with markdown text, converted HTML, and
            title if detected.

        Raises:
            ValueError: If the file extension is not supported.
        """
        if file_path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"MarkItDown does not support {file_path.suffix} files")

        start = time.perf_counter()
        result = self.markitdown.convert(str(file_path))

        md_text = result.markdown or ""
        html = markdown_to_html(md_text)
        duration = time.perf_counter() - start

        logger.info(
            "ocr.markitdown.done",
            file=str(file_path),
            duration_seconds=round(duration, 4),
        )

        return OCRResult(
            text=md_text,
            html=html,
            provider="markitdown",
            title=result.title,
            duration_seconds=duration,
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m donna.core.ocr.markitdown_ <file_path>")
        sys.exit(1)

    strategy = MarkItDownStrategy()
    result = strategy.extract(Path(sys.argv[1]))
    print(f"Provider: {result.provider}")
    print(f"Title: {result.title}")
    print(f"Text length: {len(result.text)}")
    print(f"HTML length: {len(result.html or '')}")
    print(f"Duration: {result.duration_seconds:.3f}s")
