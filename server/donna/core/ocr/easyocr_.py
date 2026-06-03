"""EasyOCR-based document extraction strategy.

Raw OCR via EasyOCR, rasterising PDF pages with PyMuPDF. Purpose-built
for scanned / photographed documents where layout analysis fails — e.g.
phone photos of identity cards, passports, receipts.

Satisfies the ``OCRStrategy`` Protocol. No layout analysis, no table
detection — use ``DoclingStrategy`` if you need those. This class is
for scanned content where the layout *is* the image and the only win
is getting the text out.

Returns joined text in reading order (top-to-bottom, left-to-right).
HTML is a minimal ``<p>``-wrapped rendering; nothing semantic.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from donna.core.logging import get_logger
from donna.core.ocr.base import OCRResult

logger = get_logger(__name__)

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".gif"}
)
PDF_EXTENSIONS = frozenset({".pdf"})

# Lambda runs as a non-root user with read-only HOME, so EasyOCR cannot
# fall back to ``~/.EasyOCR``. Models are baked into the image at this
# path in the worker-base Dockerfile; keep the two in sync.
_DEFAULT_MODULE_PATH = "/opt/easyocr"


class EasyOCRStrategy:
    """Raw OCR via EasyOCR with PyMuPDF rasterisation.

    EasyOCR's ``Reader`` is initialised lazily (model load is ~5s per
    language) and its ``readtext`` call is serialised via a lock —
    EasyOCR is not thread-safe.

    Attributes:
        languages: EasyOCR language codes (default ``("ro", "en")``).
        max_edge_px: Longest output edge in pixels after rasterisation.
            Caps memory for phone-scan PDFs whose page boxes can be
            3024×4032 pt — rasterising those at 300 DPI explodes into
            multi-hundred-MB PNGs. 1800 px is plenty for ID-card text
            (CNP / full name) while fitting inside a 3 GB Lambda with
            EasyOCR + PyTorch already loaded.
        min_confidence: Minimum confidence threshold for including a
            detected text box (0.0–1.0). Default 0.0 keeps everything
            and lets downstream classification judge.
        gpu: Pass through to EasyOCR. Default False (Lambda has no GPU).
    """

    def __init__(
        self,
        languages: tuple[str, ...] | list[str] | None = None,
        max_edge_px: int = 1800,
        min_confidence: float = 0.0,
        gpu: bool = False,
    ) -> None:
        self.languages: list[str] = list(languages) if languages else ["ro", "en"]
        self.max_edge_px = max_edge_px
        self.min_confidence = min_confidence
        self._gpu = gpu
        self._reader: Any = None
        self._lock = threading.Lock()

    def _get_reader(self) -> Any:
        """Lazily build the EasyOCR ``Reader`` (thread-safe double-check).

        Models live at ``$EASYOCR_MODULE_PATH`` (default ``/opt/easyocr``).
        Passing explicit directories prevents EasyOCR from touching
        ``$HOME/.EasyOCR`` — HOME on Lambda is read-only. We also set
        ``download_enabled=False`` so any missing-model path fails loud
        at init instead of silently attempting a network fetch.
        """
        if self._reader is not None:
            return self._reader
        with self._lock:
            if self._reader is None:
                import easyocr
                import torch

                # Lambda has no GPU and limited RAM. Multiple BLAS /
                # intra-op threads bloat resident memory with per-thread
                # workspaces without speeding up a single-page OCR call.
                torch.set_num_threads(1)

                base = os.environ.get("EASYOCR_MODULE_PATH", _DEFAULT_MODULE_PATH)
                model_dir = f"{base}/model"
                user_dir = f"{base}/user_network"
                logger.info(
                    "ocr.easyocr.reader_init",
                    languages=self.languages,
                    model_storage_directory=model_dir,
                )
                self._reader = easyocr.Reader(
                    self.languages,
                    gpu=self._gpu,
                    model_storage_directory=model_dir,
                    user_network_directory=user_dir,
                    download_enabled=False,
                )
        return self._reader

    def extract(self, file_path: Path) -> OCRResult:
        """Extract text from an image or PDF using EasyOCR.

        Args:
            file_path: Path to a PDF or supported image file.

        Returns:
            ``OCRResult`` with markdown-joined text, minimal HTML,
            page count, and provider metadata.

        Raises:
            ValueError: If the file extension is neither PDF nor a
                supported image format.
            FileNotFoundError: If the file does not exist.
        """
        suffix = file_path.suffix.lower()
        start = time.perf_counter()

        if suffix in PDF_EXTENSIONS:
            page_texts, page_count = self._extract_pdf(file_path)
        elif suffix in IMAGE_EXTENSIONS:
            page_texts = [self._ocr_bytes(file_path.read_bytes())]
            page_count = 1
        else:
            raise ValueError(f"EasyOCRStrategy does not support {suffix} files")

        text = "\n\n".join(t for t in page_texts if t)
        html = "\n".join(
            f"<p>{_escape_html(line)}</p>"
            for page in page_texts
            for line in page.splitlines()
            if line
        )
        duration = time.perf_counter() - start

        logger.info(
            "ocr.easyocr.done",
            pages=page_count,
            chars=len(text),
            duration_seconds=round(duration, 3),
        )

        return OCRResult(
            text=text,
            html=html,
            provider="easyocr",
            page_count=page_count,
            metadata={
                "languages": list(self.languages),
                "pages": len(page_texts),
            },
            duration_seconds=duration,
        )

    def _extract_pdf(self, pdf_path: Path) -> tuple[list[str], int]:
        import fitz

        doc = fitz.open(str(pdf_path))
        try:
            texts = [self._ocr_page(doc[i]) for i in range(len(doc))]
            return texts, len(doc)
        finally:
            doc.close()

    def _ocr_page(self, page: Any) -> str:
        import fitz

        rect = page.rect
        longest = max(rect.width, rect.height)
        zoom = self.max_edge_px / longest if longest > 0 else 1.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return self._ocr_bytes(pix.tobytes("png"))

    def _ocr_bytes(self, image_bytes: bytes) -> str:
        reader = self._get_reader()
        with self._lock:
            boxes = reader.readtext(image_bytes, detail=1, paragraph=False)

        filtered = [
            (bbox, text)
            for bbox, text, conf in boxes
            if conf >= self.min_confidence and text and text.strip()
        ]
        filtered.sort(key=lambda bt: (_top(bt[0]), _left(bt[0])))
        return "\n".join(text for _bbox, text in filtered)


def _top(bbox: Any) -> float:
    return min(float(pt[1]) for pt in bbox)


def _left(bbox: Any) -> float:
    return min(float(pt[0]) for pt in bbox)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
