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


if __name__ == "__main__":
    # Run: `python -m donna.cortex.ocr` (from `server/`)
    # Module imports Django storage at top — bootstrap settings.
    import logging, os, django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")
    django.setup()
    # Mute structlog noise so the demo output stays readable.
    logging.getLogger("donna.core.ocr").setLevel(logging.ERROR)

    svc = OCRService()

    print("── Wired OCR facade ────────────────────────────────────────")
    facade = svc._facade
    strategies = getattr(facade, "_strategies", None) or getattr(facade, "strategies", None)
    print(f"  available strategies: {[type(s).__name__ for s in (strategies or [])]}")

    print("\n── extract() — dummy blob ───────────────────────────────────")
    # The default facade ships llm + easyocr; neither handles plain text.
    # In a real run, hand it a .pdf or .png blob and it walks the chain.
    blob = b"% pretend this is PDF bytes"
    try:
        result = svc.extract(blob, suffix=".pdf")
        print(f"  OK  markdown[:120] = {result.markdown[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  EXPECTED FAIL — {type(exc).__name__}: {str(exc)[:160]}")

    print("\n── suffix normalisation: 'pdf' → '.pdf' ─────────────────────")
    try:
        svc.extract(blob, suffix="pdf")  # no leading dot — service prepends it
        print("  OK  dispatched (suffix normalised before strategy lookup)")
    except Exception as exc:  # noqa: BLE001
        print(f"  dispatched then EXPECTED FAIL — {type(exc).__name__}")

    print("\n── extract_storage_key() — needs default_storage; skipped here.")
