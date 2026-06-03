"""Docling document extraction strategy.

Uses IBM Docling to convert documents to markdown and HTML with rich
metadata extraction including tables, page dimensions, and provenance.
Docling is the only strategy that produces native HTML — no
``markdown_to_html`` conversion needed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, ClassVar

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.document_converter import (
    AsciiDocFormatOption,
    DocumentConverter,
    ExcelFormatOption,
    PdfFormatOption,
    PowerpointFormatOption,
    WordFormatOption,
)

from donna.core.logging import get_logger
from donna.core.ocr.base import OCRResult

logger = get_logger(__name__)


class DoclingStrategy:
    """Document extraction using IBM Docling.

    Supports the widest range of structured document formats with the
    richest metadata output. Initialises a ``DocumentConverter`` once
    and reuses it across calls.

    The ``extract()`` method satisfies the ``OCRStrategy`` Protocol.
    Additional methods (``extract_with_range``, ``extract_from_stream``)
    are Docling-specific extras not called by the facade.

    Attributes:
        SUPPORTED_FORMATS: Mapping of file extensions to Docling
            ``InputFormat`` enum values.
        converter: Reusable ``DocumentConverter`` instance.
        pipeline_options: PDF pipeline configuration (OCR, tables,
            image scale).
    """

    SUPPORTED_FORMATS: ClassVar[dict[str, InputFormat]] = {
        ".pdf": InputFormat.PDF,
        ".docx": InputFormat.DOCX,
        ".xlsx": InputFormat.XLSX,
        ".xls": InputFormat.XLSX,
        ".pptx": InputFormat.PPTX,
        ".ppt": InputFormat.PPTX,
        ".csv": InputFormat.CSV,
        ".png": InputFormat.IMAGE,
        ".jpg": InputFormat.IMAGE,
        ".jpeg": InputFormat.IMAGE,
        ".tiff": InputFormat.IMAGE,
        ".tif": InputFormat.IMAGE,
        ".bmp": InputFormat.IMAGE,
        ".webp": InputFormat.IMAGE,
        ".html": InputFormat.HTML,
        ".htm": InputFormat.HTML,
        ".md": InputFormat.MD,
        ".markdown": InputFormat.MD,
        ".adoc": InputFormat.ASCIIDOC,
        ".asciidoc": InputFormat.ASCIIDOC,
    }

    def __init__(self, ocr_enabled: bool = True, **kwargs: Any) -> None:
        """Initialise the Docling converter with pipeline options.

        Args:
            ocr_enabled: Whether to enable Docling's built-in EasyOCR
                engine for scanned pages within documents.
            **kwargs: Additional keyword arguments passed to
                ``DocumentConverter``.
        """
        self._ocr_enabled = ocr_enabled

        self.pipeline_options = PdfPipelineOptions()
        self.pipeline_options.do_ocr = ocr_enabled
        self.pipeline_options.do_table_structure = True
        self.pipeline_options.table_structure_options.do_cell_matching = True
        self.pipeline_options.ocr_options = EasyOcrOptions()
        self.pipeline_options.images_scale = 2
        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        format_options = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options),
            InputFormat.PPTX: PowerpointFormatOption(
                pipeline_options=self.pipeline_options
            ),
            InputFormat.DOCX: WordFormatOption(),
            InputFormat.XLSX: ExcelFormatOption(),
            InputFormat.ASCIIDOC: AsciiDocFormatOption(),
        }

        self.converter = DocumentConverter(format_options=format_options, **kwargs)

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text from a document using Docling.

        Converts the file using the pre-configured ``DocumentConverter``
        and returns both native markdown and HTML.

        Args:
            file_path: Path to the document file.

        Returns:
            ``OCRResult`` with markdown, native HTML, page count,
            title, and structured metadata (tables, pages).

        Raises:
            ValueError: If the file extension is not supported.
        """
        if file_path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Docling does not support {file_path.suffix} files")

        start = time.perf_counter()
        conv = self.converter.convert(str(file_path))
        duration = time.perf_counter() - start
        return self._conversion_to_ocr_result(conv, duration)

    def extract_with_range(
        self,
        file_path: Path,
        page_range: tuple[int, int],
    ) -> OCRResult:
        """Extract a subset of pages from a document.

        Docling-specific extra — not part of the ``OCRStrategy`` Protocol.

        Args:
            file_path: Path to the document file.
            page_range: Tuple of ``(start, end)`` page numbers
                (1-based, inclusive).

        Returns:
            ``OCRResult`` for the specified page range.

        Raises:
            ValueError: If the file extension is not supported.
        """
        if file_path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Docling does not support {file_path.suffix} files")

        start = time.perf_counter()
        conv = self.converter.convert(str(file_path), page_range=page_range)
        duration = time.perf_counter() - start
        return self._conversion_to_ocr_result(conv, duration)

    def extract_from_stream(self, stream: DocumentStream) -> OCRResult:
        """Extract text from an in-memory document stream.

        Docling-specific extra — not part of the ``OCRStrategy`` Protocol.
        Accepts a ``DocumentStream`` for cases where the document is
        already in memory (e.g. from an HTTP upload or S3 fetch).

        Args:
            stream: A Docling ``DocumentStream`` wrapping in-memory bytes.

        Returns:
            ``OCRResult`` with markdown, native HTML, and metadata.
        """
        start = time.perf_counter()
        conv = self.converter.convert(stream)
        duration = time.perf_counter() - start
        return self._conversion_to_ocr_result(conv, duration)

    def _conversion_to_ocr_result(
        self, conv: Any, duration_seconds: float
    ) -> OCRResult:
        """Build an ``OCRResult`` from a Docling conversion result.

        Extracts markdown, HTML, page count, title, and structured
        metadata (tables summary, page dimensions) from the
        ``DoclingDocument``.

        Args:
            conv: Raw conversion result from ``DocumentConverter.convert()``.
            duration_seconds: Elapsed wall-clock time for the conversion.

        Returns:
            Populated ``OCRResult`` instance.
        """
        doc = conv.document
        md = doc.export_to_markdown()
        html = doc.export_to_html()

        pages = getattr(doc, "pages", None)
        page_count = len(pages) if pages else None

        title: str | None = getattr(doc, "name", None) or None
        origin = getattr(doc, "origin", None)
        if title is None and origin is not None:
            title = getattr(origin, "filename", None)

        tables = getattr(doc, "tables", None) or []
        table_summary: list[dict[str, Any]] = []
        for i, t in enumerate(tables[:50]):
            table_summary.append(
                {
                    "index": i,
                    "self_ref": str(getattr(t, "self_ref", "")),
                }
            )

        pages_meta: list[dict[str, Any]] = []
        if pages:
            for p in pages[:20]:
                pages_meta.append(
                    {
                        "page_no": getattr(p, "page_no", None),
                        "size": getattr(p, "size", None),
                    }
                )

        metadata: dict[str, Any] = {
            "tables": table_summary,
            "pages": pages_meta,
            "tables_total": len(tables),
        }

        logger.info(
            "ocr.docling.done",
            pages=page_count,
            duration_seconds=round(duration_seconds, 4),
        )

        return OCRResult(
            text=md,
            html=html,
            provider="docling",
            page_count=page_count,
            title=str(title) if title else None,
            metadata=metadata,
            duration_seconds=duration_seconds,
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m donna.core.ocr.docling_ <file_path>")
        sys.exit(1)

    docling = DoclingStrategy()
    result = docling.extract(Path(sys.argv[1]))
    print(result)
