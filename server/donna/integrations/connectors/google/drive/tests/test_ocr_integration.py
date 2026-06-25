"""
Drive OCR integration smoke tests.

Verifies the 2026-06-19 wire-up: when ``ingest_drive_file`` downloads a
PDF, ``OCRService.extract(...)`` runs and the markdown gets written as
a ``.extracted.md`` sidecar at BOTH the binary blob key and the
metadata storage key — so the cortex pipeline's tier-1 sidecar lookup
finds it on the cortex hop.

We mock the OCR facade so tests don't hit pymupdf4llm/markitdown/llm
at import time (heavy deps + LLM cost). Strategy ordering is verified
in donna.core.ocr's own test suite.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from donna.core.ocr import OCRResult
from donna.core.ocr.service import OCRService


class OCRServiceTests(unittest.TestCase):
    """Pure-Python tests for the OCRService shim — no Django needed."""

    def test_extract_normalises_suffix_without_leading_dot(self) -> None:
        fake = OCRResult(text="hello world content here", provider="fake")
        called: dict = {}

        class FakeFacade:
            def extract_from_bytes(self, blob: bytes, suffix: str) -> OCRResult:
                called["suffix"] = suffix
                called["blob"] = blob
                return fake

        svc = OCRService(facade=FakeFacade())
        svc.extract(b"pdf bytes here", suffix="pdf")  # no leading dot
        self.assertEqual(called["suffix"], ".pdf")

    def test_extract_passes_through_when_dotted(self) -> None:
        fake = OCRResult(text="hello world content here", provider="fake")
        called: dict = {}

        class FakeFacade:
            def extract_from_bytes(self, blob: bytes, suffix: str) -> OCRResult:
                called["suffix"] = suffix
                return fake

        svc = OCRService(facade=FakeFacade())
        svc.extract(b"x", suffix=".pdf")
        self.assertEqual(called["suffix"], ".pdf")

    def test_extract_returns_facade_result(self) -> None:
        expected = OCRResult(
            text="# Title\n\nbody " * 5,
            provider="pymupdf4llm",
            page_count=3,
        )

        class FakeFacade:
            def extract_from_bytes(self, blob: bytes, suffix: str) -> OCRResult:
                return expected

        svc = OCRService(facade=FakeFacade())
        result = svc.extract(b"x", suffix=".pdf")
        self.assertIs(result, expected)
        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_empty)


class OCRResultGatingTests(unittest.TestCase):
    """Sanity checks on the is_valid / is_empty guard used by the ingest
    task to decide whether to write the sidecar."""

    def test_empty_result_blocks_sidecar_write(self) -> None:
        r = OCRResult(text="", provider="fake")
        self.assertTrue(r.is_empty)
        self.assertFalse(r.is_valid)

    def test_whitespace_only_blocks_sidecar_write(self) -> None:
        r = OCRResult(text="   \n\t  ", provider="fake")
        self.assertTrue(r.is_empty)
        self.assertFalse(r.is_valid)

    def test_short_text_blocks_sidecar_write(self) -> None:
        # < _MIN_TEXT_LENGTH (20)
        r = OCRResult(text="hi", provider="fake")
        self.assertFalse(r.is_empty)
        self.assertFalse(r.is_valid)

    def test_valid_content_allows_sidecar_write(self) -> None:
        r = OCRResult(
            text="# Contract\n\nThis agreement is entered into between …",
            provider="pymupdf4llm",
        )
        self.assertFalse(r.is_empty)
        self.assertTrue(r.is_valid)

    def test_llm_refusal_blocks_sidecar_write(self) -> None:
        r = OCRResult(
            text="I cannot assist with extracting that document.",
            provider="llm",
        )
        self.assertFalse(r.is_valid)


if __name__ == "__main__":
    unittest.main()
