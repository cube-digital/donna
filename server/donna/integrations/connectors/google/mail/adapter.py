"""
GmailMessageAdapter — renders a Gmail full-format message to Donna's
adapter surface (to_text / to_markdown / to_json / metadata + identity).

Expected raw shape::

    raw = {"message": <users.messages.get response, format=full>}

Gmail message bodies live in nested MIME parts. The adapter walks the
tree, prefers ``text/plain``, falls back to ``text/html`` (stripped to
text), and exposes the structured payload as ``to_json``.
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from email.utils import getaddresses
from typing import Any

from donna.core.integrations import BaseEntityAdapter


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t ]+")


def _b64url_decode(data: str | None) -> bytes:
    if not data:
        return b""
    # Gmail uses URL-safe base64 with stripped padding.
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _iter_parts(payload: dict[str, Any]):
    """Yield every leaf MIME part in a Gmail message payload tree."""
    if not payload:
        return
    parts = payload.get("parts")
    if not parts:
        yield payload
        return
    for part in parts:
        yield from _iter_parts(part)


def _headers_to_map(headers: list[dict] | None) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in (headers or [])}


def _html_to_text(html_body: str) -> str:
    """Best-effort HTML → text. Cheap stripping, not a full parser."""
    no_tags = _HTML_TAG_RE.sub(" ", html_body)
    unescaped = html.unescape(no_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


class GmailMessageAdapter(BaseEntityAdapter):
    """Adapter for one Gmail message (full format).

    Phase 2 (2026-06-15): emits ``CanonicalEntity(entity_type="email")``
    via ``to_canonical()``. Required EmailExtensions nav: ``thread_id``.
    """

    canonical_type = "email"

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def _message(self) -> dict[str, Any]:
        return self.raw.get("message") or {}

    @property
    def _payload(self) -> dict[str, Any]:
        return self._message.get("payload") or {}

    @property
    def _headers(self) -> dict[str, str]:
        return _headers_to_map(self._payload.get("headers"))

    # ── BaseAdapter — required ──────────────────────────────────────────────
    def external_id(self) -> str:
        message_id = self._message.get("id")
        if not message_id:
            raise ValueError("Gmail message payload missing 'id'")
        return str(message_id)

    def title(self) -> str:
        return self._headers.get("subject") or "(no subject)"

    def occurred_at(self) -> datetime:
        # internalDate is ms since epoch (string), per Gmail API spec.
        internal = self._message.get("internalDate")
        if internal:
            return datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
        # Fallback to RFC2822 Date header if internalDate missing.
        from email.utils import parsedate_to_datetime
        date_hdr = self._headers.get("date")
        if date_hdr:
            try:
                dt = parsedate_to_datetime(date_hdr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                pass
        return datetime.now(tz=timezone.utc)

    def to_json(self) -> dict:
        """Return Gmail's structured payload verbatim — what we land in storage."""
        return self._message

    # ── Optional ────────────────────────────────────────────────────────────
    def to_text(self) -> str:
        """Concatenate all text parts. Prefers text/plain over text/html."""
        plain_chunks: list[str] = []
        html_chunks: list[str] = []
        for part in _iter_parts(self._payload):
            mime = part.get("mimeType", "")
            body = (part.get("body") or {}).get("data")
            if not body:
                continue
            decoded = _b64url_decode(body).decode("utf-8", errors="replace")
            if mime == "text/plain":
                plain_chunks.append(decoded)
            elif mime == "text/html":
                html_chunks.append(_html_to_text(decoded))
        if plain_chunks:
            return "\n\n".join(c.strip() for c in plain_chunks if c.strip())
        return "\n\n".join(c for c in html_chunks if c)

    def to_markdown(self) -> str:
        h = self._headers
        lines: list[str] = [
            f"# {self.title()}",
            "",
            f"**From:** {h.get('from', '')}  ",
            f"**To:** {h.get('to', '')}  ",
        ]
        if h.get("cc"):
            lines.append(f"**Cc:** {h['cc']}  ")
        lines.append(f"**Date:** {self.occurred_at().isoformat()}  ")
        lines.append("")
        body = self.to_text() or "_(no plain-text body)_"
        lines.append(body)
        return "\n".join(lines)

    def metadata(self) -> dict:
        h = self._headers
        msg = self._message

        def _addresses(field: str) -> list[str]:
            value = h.get(field)
            if not value:
                return []
            return [addr for _, addr in getaddresses([value]) if addr]

        return {
            "thread_id":     msg.get("threadId"),
            "label_ids":     msg.get("labelIds") or [],
            "history_id":    msg.get("historyId"),
            "internal_date": msg.get("internalDate"),
            "snippet":       msg.get("snippet"),
            "size_estimate": msg.get("sizeEstimate"),
            "from":          h.get("from"),
            "to":            _addresses("to"),
            "cc":            _addresses("cc"),
            "bcc":           _addresses("bcc"),
            "reply_to":      h.get("reply-to"),
            "subject":       h.get("subject"),
            "message_id_hdr": h.get("message-id"),
            "in_reply_to":   h.get("in-reply-to"),
        }

    # ── BaseEntityAdapter — canonical extensions ────────────────────────────
    def _extensions(self) -> dict:
        """EmailExtensions-shaped payload (nav: thread_id)."""
        h = self._headers
        msg = self._message

        def _addresses(field: str) -> list[str]:
            value = h.get(field)
            if not value:
                return []
            return [addr for _, addr in getaddresses([value]) if addr]

        participants = []
        for addr in (
            [h.get("from")] if h.get("from") else []
        ) + _addresses("to") + _addresses("cc"):
            if addr:
                participants.append({
                    "name": None,
                    "addr": addr if "@" in addr else None,
                    "role": "from" if addr == h.get("from") else "to",
                })
        # Pydantic EmailExtensions requires participants_emails as
        # list[dict{name,addr,role}].
        return {
            "thread_id":           msg.get("threadId"),
            "participants_emails": [p for p in participants if p.get("addr")],
        }
