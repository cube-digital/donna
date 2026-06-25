"""Shared binary → markdown sidecar extractor.

Connectors that store binary blobs (PDFs, images, Office docs) all need
the same processing: take the stored bytes, run the OCR ladder
(pymupdf4llm → markitdown → easyocr → llm), and write the markdown
alongside as a ``.extracted.md`` sidecar so the cortex pipeline's
tier-1 sidecar lookup picks it up on the cortex hop.

Originally implemented inline in ``drive/tasks.py`` (2026-06-19).
Extracted here so mail attachments + any future connector reuse the
same path without copy-pasting OCR plumbing.

Contract — pure function:
    1. Caller writes raw bytes to ``default_storage`` at ``bronze_key``.
    2. Caller invokes ``extract_to_sidecar(bronze_key, suffix=".pdf")``.
    3. Function reads the blob, runs OCR, writes the sidecar at
       ``<bronze_key without .json>.extracted.md`` (via
       ``bronze.sidecar_key_for``).
    4. Returns the sidecar key on success, or ``None`` if the OCR
       result was empty / invalid — caller logs + continues.

Idempotent: if the sidecar already exists at the computed path, returns
its key without re-OCRing. Safe to call on retry.
"""
from __future__ import annotations

import logging

from django.core.files.storage import default_storage

from donna.core.integrations.bronze import sidecar_key_for, write_sidecar
from donna.core.ocr.service import OCRService


logger = logging.getLogger(__name__)


def extract_to_sidecar(
    bronze_key: str,
    *,
    suffix: str,
    ocr_service: OCRService | None = None,
) -> str | None:
    """Read binary at ``bronze_key``, OCR to markdown, write sidecar.

    Args:
        bronze_key: ``default_storage`` key where the raw bytes live.
            Bronze keys end in ``.json`` regardless of content, so the
            caller must pass ``suffix`` explicitly.
        suffix: True file extension (e.g. ``".pdf"``). Drives strategy
            ordering inside the OCR facade. Leading dot optional —
            ``OCRService.extract`` normalises.
        ocr_service: Injectable for tests. Defaults to ``OCRService()``.

    Returns:
        Sidecar key on success, ``None`` when extraction was empty /
        invalid / the blob was missing.
    """
    sidecar = sidecar_key_for(bronze_key)
    if default_storage.exists(sidecar):
        return sidecar

    if not default_storage.exists(bronze_key):
        logger.warning(
            "binary_extract_missing_blob",
            extra={"bronze_key": bronze_key},
        )
        return None

    with default_storage.open(bronze_key, "rb") as f:
        raw = f.read()

    svc = ocr_service or OCRService()

    try:
        result = svc.extract(raw, suffix=suffix)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "binary_extract_failed",
            extra={
                "bronze_key": bronze_key,
                "suffix":     suffix,
                "error":      str(exc),
            },
        )
        return None

    if not result.is_valid or result.is_empty:
        logger.info(
            "binary_extract_empty",
            extra={
                "bronze_key": bronze_key,
                "provider":   result.provider,
            },
        )
        return None

    written = write_sidecar(default_storage, bronze_key, result.text)
    logger.info(
        "binary_extract_written",
        extra={
            "bronze_key":  bronze_key,
            "sidecar_key": written,
            "provider":    result.provider,
            "text_len":    len(result.text),
            "duration":    result.duration_seconds,
        },
    )
    return written
