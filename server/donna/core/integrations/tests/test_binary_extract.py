"""
Tests for the shared binary → sidecar extractor (E1, 2026-06-19).

Pure-Python coverage of the contract:
- happy path: bytes saved at bronze_key → OCR runs → sidecar written
- idempotent: second call returns existing key, no re-OCR
- empty result: returns None, no sidecar
- invalid result: same — no sidecar, returns None
- missing blob: returns None
- OCR raises: caught, returns None

Uses InMemoryStorage (auto-injected in settings when tests detected) so
nothing escapes to the host filesystem.
"""
from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

from donna.core.integrations.binary_extract import extract_to_sidecar
from donna.core.integrations.bronze import sidecar_key_for
from donna.core.ocr import OCRResult


class _FakeService:
    """Stand-in for OCRService; captures inputs, returns scripted result."""

    def __init__(self, result: OCRResult, raise_exc: Exception | None = None):
        self.result = result
        self.raise_exc = raise_exc
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, blob: bytes, suffix: str) -> OCRResult:
        self.calls.append((blob, suffix))
        if self.raise_exc:
            raise self.raise_exc
        return self.result


class ExtractToSidecarHappyPathTests(TestCase):
    def test_writes_sidecar_with_extracted_text(self) -> None:
        bronze_key = "ws-x/google/drive/files-bin/file-1/abcd1234.json"
        default_storage.save(bronze_key, ContentFile(b"%PDF-1.4 fake pdf bytes"))

        fake = _FakeService(OCRResult(
            text="# Contract\n\nThis agreement is entered into...",
            provider="pymupdf4llm",
        ))

        sidecar = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)

        self.assertEqual(sidecar, sidecar_key_for(bronze_key))
        self.assertTrue(default_storage.exists(sidecar))
        with default_storage.open(sidecar, "rb") as f:
            self.assertIn(b"Contract", f.read())
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][1], ".pdf")

    def test_caller_supplied_suffix_passed_through(self) -> None:
        bronze_key = "ws-x/google/mail/attachments/m1:a1/aaaaaaaa.json"
        default_storage.save(bronze_key, ContentFile(b"binary blob"))

        fake = _FakeService(OCRResult(text="extracted body here " * 5, provider="markitdown"))

        extract_to_sidecar(bronze_key, suffix=".docx", ocr_service=fake)

        self.assertEqual(fake.calls[0][1], ".docx")


class ExtractToSidecarIdempotencyTests(TestCase):
    def test_skips_ocr_when_sidecar_already_present(self) -> None:
        bronze_key = "ws-y/google/drive/files-bin/file-2/cafebabe.json"
        default_storage.save(bronze_key, ContentFile(b"PDF bytes"))

        fake = _FakeService(OCRResult(text="first extraction here..." * 5, provider="fake"))
        first = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)
        self.assertEqual(len(fake.calls), 1)

        second = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)
        self.assertEqual(second, first)
        self.assertEqual(len(fake.calls), 1, "OCR re-run when sidecar already existed")


class ExtractToSidecarGuardsTests(TestCase):
    def test_returns_none_when_blob_missing(self) -> None:
        fake = _FakeService(OCRResult(text="x" * 50, provider="fake"))
        result = extract_to_sidecar(
            "ws-z/missing/file/key/00000000.json",
            suffix=".pdf",
            ocr_service=fake,
        )
        self.assertIsNone(result)
        self.assertEqual(fake.calls, [], "OCR ran on missing blob")

    def test_returns_none_when_ocr_result_empty(self) -> None:
        bronze_key = "ws-z/google/drive/files-bin/file-3/00112233.json"
        default_storage.save(bronze_key, ContentFile(b"PDF"))

        fake = _FakeService(OCRResult(text="", provider="fake"))
        result = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)

        self.assertIsNone(result)
        self.assertFalse(default_storage.exists(sidecar_key_for(bronze_key)))

    def test_returns_none_when_ocr_result_too_short(self) -> None:
        # < _MIN_TEXT_LENGTH (20) trips is_valid=False
        bronze_key = "ws-z/google/drive/files-bin/file-4/44556677.json"
        default_storage.save(bronze_key, ContentFile(b"PDF"))

        fake = _FakeService(OCRResult(text="hi", provider="fake"))
        result = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)

        self.assertIsNone(result)
        self.assertFalse(default_storage.exists(sidecar_key_for(bronze_key)))

    def test_returns_none_when_ocr_raises(self) -> None:
        bronze_key = "ws-z/google/drive/files-bin/file-5/8899aabb.json"
        default_storage.save(bronze_key, ContentFile(b"PDF"))

        fake = _FakeService(
            OCRResult(text="", provider="fake"),
            raise_exc=RuntimeError("ocr blew up"),
        )
        result = extract_to_sidecar(bronze_key, suffix=".pdf", ocr_service=fake)

        self.assertIsNone(result)
        self.assertFalse(default_storage.exists(sidecar_key_for(bronze_key)))
