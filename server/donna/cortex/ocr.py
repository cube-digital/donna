"""
OCRService — Cortex-facing boundary around ``donna.core.ocr``.

The OCR engine itself (Strategy + Facade + four backends) lives in
``donna/core/ocr/`` so other apps can reuse it. This shim:

- Hides ``create_ocr()`` so callers don't have to know the factory
  signature.
- Adds ``extract_storage_key`` for the common path: ``DeliveryPackage``
  rows hold a ``storage_key`` referring to ``default_storage``; the
  Cortex pipeline reads the blob, picks a suffix, and delegates.
"""
from __future__ import annotations

from pathlib import Path

from django.core.files.storage import default_storage

from donna.core.ocr import OCRFacade, OCRResult, create_ocr


class OCRService:
    """Cortex's single import point for OCR."""

    def __init__(self, facade: OCRFacade | None = None) -> None:
        self._facade = facade or create_ocr()

    def extract(self, blob: bytes, suffix: str) -> OCRResult:
        """Extract markdown from raw bytes.

        Args:
            blob: Raw file content.
            suffix: File extension (e.g. ``".pdf"``); drives strategy
                ordering inside the facade.
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
