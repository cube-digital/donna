"""PyMuPDF4LLM extraction strategy.

Converts PDF documents to markdown using PyMuPDF4LLM, with optional
per-page chunks for metadata (TOC, layout boxes).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pymupdf4llm

from donna.core.logging import get_logger
from donna.core.ocr.base import OCRResult
from donna.core.ocr.utils import markdown_to_html

logger = get_logger(__name__)


class PyMuPDF4LLMStrategy:
    """PDF-to-markdown extraction using PyMuPDF4LLM.

    Fast local strategy. Only supports PDF files. When ``page_chunks=True``,
    the library returns a list of per-page dicts with ``text``, ``metadata``,
    ``toc_items``, and ``page_boxes`` (layout).
    """

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text from a PDF using PyMuPDF4LLM.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ``OCRResult`` with markdown text, HTML, and metadata.

        Raises:
            ValueError: If the file is not a PDF.
        """
        if file_path.suffix.lower() != ".pdf":
            raise ValueError(f"PyMuPDF4LLM only supports PDF, got: {file_path.suffix}")

        start = time.perf_counter()
        raw = pymupdf4llm.to_markdown(str(file_path), page_chunks=True)

        if isinstance(raw, str):
            md_text = raw
            page_count: int | None = None
            metadata: dict[str, Any] = {
                "page_chunks": False,
                "doc_metadata": {},
            }
        elif isinstance(raw, list):
            md_text = "\n\n".join(
                (chunk.get("text") or "") if isinstance(chunk, dict) else ""
                for chunk in raw
            )
            page_count = len(raw)
            doc_metadata: dict[str, Any] = {}
            toc_items: list[Any] = []
            table_boxes: list[dict[str, Any]] = []
            if raw:
                first = raw[0]
                if isinstance(first, dict):
                    doc_metadata = dict(first.get("metadata") or {})
                for chunk in raw:
                    if not isinstance(chunk, dict):
                        continue
                    toc_items.extend(chunk.get("toc_items") or [])
                    for box in chunk.get("page_boxes") or []:
                        if isinstance(box, dict) and box.get("class") == "table":
                            table_boxes.append(box)
            metadata = {
                "toc": toc_items,
                "tables": table_boxes,
                "doc_metadata": doc_metadata,
            }
        else:
            md_text = str(raw)
            page_count = None
            metadata = {"unexpected_type": type(raw).__name__}

        html = markdown_to_html(md_text)
        title = None
        if isinstance(metadata.get("doc_metadata"), dict):
            title = metadata["doc_metadata"].get("title")

        duration = time.perf_counter() - start
        logger.info(
            "ocr.pymupdf4llm.done",
            file=str(file_path),
            pages=page_count,
            duration_seconds=round(duration, 4),
        )

        return OCRResult(
            text=md_text,
            html=html,
            provider="pymupdf4llm",
            page_count=page_count,
            title=title,
            metadata=metadata,
            duration_seconds=duration,
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m donna.core.ocr.pymupdf4llm_ <pdf_path>")
        sys.exit(1)

    strategy = PyMuPDF4LLMStrategy()
    result = strategy.extract(Path(sys.argv[1]))
    print(f"Provider: {result.provider}")
    print(f"Pages: {result.page_count}")
    print(f"Text length: {len(result.text)}")
    print(f"Duration: {result.duration_seconds:.3f}s")
