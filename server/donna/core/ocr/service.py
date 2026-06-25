"""
OCRService — thin shim around ``donna.core.ocr.OCRFacade`` for callers
that only need ``bytes → markdown`` and don't want to deal with the
factory + suffix-normalisation glue.

Previously lived at ``donna/cortex/ocr.py``; was deleted in the
2026-06-15 refactor when the cortex pipeline dropped its tier-3 OCR
fallback. Re-introduced 2026-06-19 to give the Drive connector a clean
hook for PDF text extraction (binary files were landing in cortex as
title-only).

Usage::

    result = OCRService().extract(pdf_bytes, suffix=".pdf")
    if result.is_valid and not result.is_empty:
        write_sidecar(default_storage, bronze_key, result.text)
"""
from __future__ import annotations

from pathlib import Path

from django.core.files.storage import default_storage

from donna.core.ocr import OCRFacade, OCRResult, create_ocr


class OCRService:
    """Single import point for callers that just want extracted text."""

    def __init__(self, facade: OCRFacade | None = None) -> None:
        self._facade = facade or create_ocr()

    def extract(self, blob: bytes, suffix: str) -> OCRResult:
        """Extract markdown from raw bytes.

        Args:
            blob:   Raw file content.
            suffix: File extension (e.g. ``".pdf"``); drives strategy
                ordering inside the facade. Leading dot added if missing.
        """
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        return self._facade.extract_from_bytes(blob, suffix=suffix)

    def extract_storage_key(self, storage_key: str) -> OCRResult:
        """Extract from a ``default_storage`` key.

        Reads the blob via ``default_storage.open(...)`` and dispatches
        to ``extract`` with the suffix derived from the key.
        """
        suffix = Path(storage_key).suffix or ".bin"
        with default_storage.open(storage_key, mode="rb") as f:
            blob = f.read()
        return self.extract(blob, suffix=suffix)
