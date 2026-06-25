"""
Gmail attachment ingestion tests (E3, 2026-06-19).

Direct coverage of ``_ingest_attachments`` — the helper inside
``mail/tasks.py`` that walks a Gmail message's MIME tree, downloads
PDF attachments, runs OCR via the shared ``extract_to_sidecar``, and
emits child DeliveryPackages with ``canonical_type="doc"``.

We bypass the OAuth + Connection fixturing of the full
``ingest_gmail_message`` task by calling the helper directly with a
real workspace + saved parent DP + a fake Gmail client. Cortex pipeline
is patched to a no-op so the test stays focused on attachment plumbing.

OCRService is also patched (via ``extract_to_sidecar``'s ``OCRService``
import) so tests don't hit pymupdf4llm / markitdown / llm.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.test import TestCase

from donna.core.ocr import OCRResult
from donna.integrations.connectors.google.mail.tasks import _ingest_attachments
from donna.integrations.models import DeliveryPackage
from donna.workspaces.models import Workspace


def _b64url(blob: bytes) -> str:
    """Gmail-style: URL-safe base64 with trailing padding stripped."""
    return base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


class _FakeOCRService:
    """Returns a scripted result; counts calls."""

    def __init__(self, result: OCRResult):
        self.result = result
        self.calls = 0

    def extract(self, blob: bytes, suffix: str) -> OCRResult:
        self.calls += 1
        return self.result


class _FakeGmailClient:
    """Stand-in for GmailClient with a scripted ``get_attachment``."""

    def __init__(self, attachments: dict[str, bytes]):
        self.attachments = attachments  # attachment_id → raw bytes
        self.fetched: list[tuple[str, str]] = []

    def get_attachment(self, message_id: str, attachment_id: str) -> dict:
        self.fetched.append((message_id, attachment_id))
        return {
            "size": len(self.attachments[attachment_id]),
            "data": _b64url(self.attachments[attachment_id]),
        }


# ── fixtures ───────────────────────────────────────────────────────────


def _make_workspace(slug: str = "test-ws") -> Workspace:
    return Workspace.objects.create(name="Test", slug=slug)


def _make_parent_dp(workspace: Workspace, msg_id: str = "msg-1") -> DeliveryPackage:
    return DeliveryPackage.objects.create(
        workspace=workspace,
        provider="gmail",
        provider_item_id=msg_id,
        provider_item_type="email",
        title="Test email",
        occurred_at=datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc),
        storage_key=f"{workspace.id}/google/mail/messages/{msg_id}/deadbeef.json",
        canonical_type="email",
        canonical_payload={},
    )


def _message_with_attachment(
    msg_id: str,
    filename: str,
    mime: str,
    *,
    attachment_id: str | None = None,
    inline_bytes: bytes | None = None,
) -> dict:
    """Synthetic Gmail message payload with one attachment part."""
    body: dict = {"size": 1024}
    if attachment_id:
        body["attachmentId"] = attachment_id
    if inline_bytes is not None:
        body["data"] = _b64url(inline_bytes)
    return {
        "id": msg_id,
        "payload": {
            "headers": [{"name": "Subject", "value": "Test"}],
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "body": {"data": _b64url(b"email body text")},
                },
                {
                    "partId": "1",
                    "mimeType": mime,
                    "filename": filename,
                    "body": body,
                },
            ],
        },
    }


# ── tests ──────────────────────────────────────────────────────────────


class AttachmentIngestHappyPathTests(TestCase):
    def test_pdf_attachment_ingested_via_get_attachment(self) -> None:
        ws = _make_workspace("ws-pdf-remote")
        parent = _make_parent_dp(ws, msg_id="m-pdf-1")
        # 10KB > _INLINE_SKIP_MIN_BYTES; non-zero content
        pdf_bytes = b"%PDF-1.4 " + (b"A" * (10 * 1024))
        client = _FakeGmailClient({"att-1": pdf_bytes})
        message = _message_with_attachment(
            "m-pdf-1", "contract.pdf", "application/pdf",
            attachment_id="att-1",
        )
        fake_ocr = _FakeOCRService(OCRResult(
            text="# Contract\n\nThis agreement is entered into ..." * 3,
            provider="pymupdf4llm",
        ))

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
            return_value=fake_ocr,
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ) as cortex_cls:
            cortex_cls.return_value.write.return_value = object()

            count = _ingest_attachments(client, str(ws.id), message, parent)

        self.assertEqual(count, 1)
        self.assertEqual(client.fetched, [("m-pdf-1", "att-1")])
        self.assertEqual(fake_ocr.calls, 1)

        # Child DP exists and is linked to parent via metadata.
        att_dp = DeliveryPackage.objects.get(
            workspace=ws, provider_item_id="m-pdf-1:att-1",
        )
        self.assertEqual(att_dp.provider, "gmail")
        self.assertEqual(att_dp.provider_item_type, "email_attachment")
        self.assertEqual(att_dp.canonical_type, "doc")
        self.assertEqual(att_dp.title, "contract.pdf")
        self.assertEqual(att_dp.metadata["parent_message_id"], "m-pdf-1")
        self.assertEqual(att_dp.metadata["parent_package_id"], str(parent.id))
        self.assertEqual(att_dp.metadata["attachment_id"], "att-1")
        self.assertEqual(att_dp.metadata["filename"], "contract.pdf")
        self.assertEqual(att_dp.canonical_payload["entity_type"], "doc")
        self.assertEqual(att_dp.canonical_payload["extensions"]["doc_type"], "other")

        # Sidecar exists at the bronze key.
        from donna.core.integrations.bronze import sidecar_key_for
        sidecar = sidecar_key_for(att_dp.storage_key)
        self.assertTrue(default_storage.exists(sidecar))

    def test_pdf_attachment_inline_data_used_without_extra_fetch(self) -> None:
        ws = _make_workspace("ws-pdf-inline")
        parent = _make_parent_dp(ws, msg_id="m-pdf-2")
        pdf_bytes = b"%PDF-1.4 " + (b"B" * (12 * 1024))
        client = _FakeGmailClient({})  # no remote fetch
        message = _message_with_attachment(
            "m-pdf-2", "spec.pdf", "application/pdf",
            inline_bytes=pdf_bytes,
        )
        fake_ocr = _FakeOCRService(OCRResult(
            text="# Spec\n\nDetailed technical specification ..." * 3,
            provider="pymupdf4llm",
        ))

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
            return_value=fake_ocr,
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ) as cortex_cls:
            cortex_cls.return_value.write.return_value = object()

            count = _ingest_attachments(client, str(ws.id), message, parent)

        self.assertEqual(count, 1)
        self.assertEqual(client.fetched, [], "remote fetch ran for inline attachment")
        self.assertEqual(fake_ocr.calls, 1)


class AttachmentIngestFilterTests(TestCase):
    def test_non_pdf_attachment_skipped(self) -> None:
        ws = _make_workspace("ws-non-pdf")
        parent = _make_parent_dp(ws, msg_id="m-img-1")
        client = _FakeGmailClient({"att-img": b"\x89PNG" + b"X" * 10_000})
        message = _message_with_attachment(
            "m-img-1", "photo.png", "image/png",
            attachment_id="att-img",
        )

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ):
            count = _ingest_attachments(client, str(ws.id), message, parent)

        self.assertEqual(count, 0)
        self.assertEqual(client.fetched, [])
        self.assertFalse(
            DeliveryPackage.objects.filter(
                workspace=ws, provider_item_type="email_attachment",
            ).exists()
        )

    def test_tiny_inline_attachment_skipped(self) -> None:
        ws = _make_workspace("ws-tiny")
        parent = _make_parent_dp(ws, msg_id="m-tiny-1")
        client = _FakeGmailClient({})
        # 100 bytes < 5KB threshold
        message = _message_with_attachment(
            "m-tiny-1", "sig.pdf", "application/pdf",
            inline_bytes=b"X" * 100,
        )

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ):
            count = _ingest_attachments(client, str(ws.id), message, parent)

        self.assertEqual(count, 0)
        self.assertFalse(
            DeliveryPackage.objects.filter(
                workspace=ws, provider_item_type="email_attachment",
            ).exists()
        )

    def test_message_without_attachments_returns_zero(self) -> None:
        ws = _make_workspace("ws-no-att")
        parent = _make_parent_dp(ws, msg_id="m-noatt-1")
        client = _FakeGmailClient({})
        message = {
            "id": "m-noatt-1",
            "payload": {
                "headers": [{"name": "Subject", "value": "Plain"}],
                "parts": [
                    {
                        "partId": "0",
                        "mimeType": "text/plain",
                        "body": {"data": _b64url(b"body only")},
                    }
                ],
            },
        }

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ):
            count = _ingest_attachments(client, str(ws.id), message, parent)

        self.assertEqual(count, 0)


class AttachmentIngestIdempotencyTests(TestCase):
    def test_second_call_upserts_same_dp(self) -> None:
        ws = _make_workspace("ws-idemp")
        parent = _make_parent_dp(ws, msg_id="m-idemp-1")
        pdf_bytes = b"%PDF " + b"C" * (8 * 1024)
        client = _FakeGmailClient({"att-id": pdf_bytes})
        message = _message_with_attachment(
            "m-idemp-1", "doc.pdf", "application/pdf",
            attachment_id="att-id",
        )
        fake_ocr = _FakeOCRService(OCRResult(
            text="extracted body text long enough to pass validity gate" * 2,
            provider="markitdown",
        ))

        with patch(
            "donna.core.integrations.binary_extract.OCRService",
            return_value=fake_ocr,
        ), patch(
            "donna.cortex.pipeline.CortexPipeline",
        ) as cortex_cls:
            cortex_cls.return_value.write.return_value = object()

            _ingest_attachments(client, str(ws.id), message, parent)
            _ingest_attachments(client, str(ws.id), message, parent)

        # Exactly one DP — second call upserted, didn't duplicate.
        att_count = DeliveryPackage.objects.filter(
            workspace=ws, provider_item_type="email_attachment",
        ).count()
        self.assertEqual(att_count, 1)
        # OCR ran only once thanks to sidecar idempotency.
        self.assertEqual(fake_ocr.calls, 1)
