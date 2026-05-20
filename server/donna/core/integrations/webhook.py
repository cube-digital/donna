"""
BaseWebhookHandler — verifies and parses incoming provider webhooks.

The default implementation handles the common HMAC-SHA256-in-header pattern
(~80% of SaaS webhooks). Providers with non-HMAC schemes (Slack request signing,
GitHub installation tokens, etc.) override `verify`.

Workspace resolution is *not* the handler's job — it lives on the connector
class itself via `IntegrationProvider.resolve_workspace(parsed)`, because the
mapping from payload to OAuthToken is provider-specific.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider

from .exceptions import WebhookPayloadInvalid, WebhookSignatureInvalid


logger = logging.getLogger(__name__)


class BaseWebhookHandler:
    """
    Default webhook handler — HMAC-SHA256 signature in a configurable header,
    JSON payload. Subclass and override for providers with custom schemes.
    """

    #: HTTP header name carrying the signature. Override for non-default.
    signature_header: str = "X-Signature"

    #: Hash algorithm used by HMAC. Override for e.g. sha1.
    signature_algo: str = "sha256"

    #: If the provider sends a prefixed signature like ``sha256=abcdef``, set
    #: this to ``"sha256="`` so it gets stripped before comparison.
    signature_prefix: str = ""

    def __init__(self, config: "OAuthProvider"):
        self.config = config

    # ── Signature verification ──────────────────────────────────────────────
    def verify(self, payload: bytes, signature: str | None) -> bool:
        """
        Verify the HMAC signature of an incoming webhook.

        Returns True on success; raises WebhookSignatureInvalid on failure.
        """
        if not signature:
            raise WebhookSignatureInvalid("missing signature header")

        secret = (self.config.webhook_secret or "")
        if not secret:
            raise WebhookSignatureInvalid(
                f"webhook_secret not configured on OAuthProvider {self.config.slug!r}"
            )

        cleaned = (
            signature[len(self.signature_prefix):]
            if self.signature_prefix and signature.startswith(self.signature_prefix)
            else signature
        )

        try:
            algo = getattr(hashlib, self.signature_algo)
        except AttributeError as exc:
            raise WebhookSignatureInvalid(
                f"unsupported signature algorithm {self.signature_algo!r}"
            ) from exc

        expected = hmac.new(secret.encode(), payload, algo).hexdigest()
        if not hmac.compare_digest(expected, cleaned):
            raise WebhookSignatureInvalid("signature does not match payload")
        return True

    # ── Parsing ─────────────────────────────────────────────────────────────
    def parse(self, payload: bytes) -> dict:
        """
        Parse the raw payload into a dict. Default: JSON.

        Override for providers using a different encoding (form-encoded, etc.).
        """
        try:
            return json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise WebhookPayloadInvalid(f"invalid JSON payload: {exc}") from exc

    def external_event_id(self, parsed: dict) -> str | None:
        """
        Optional helper: extract the provider's stable event ID from the parsed
        payload. Used for idempotency where relevant. Default tries common keys;
        return None when the provider doesn't supply one.
        """
        for key in ("event_id", "id", "event"):
            value = parsed.get(key)
            if value:
                return str(value)
        return None
