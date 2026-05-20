"""
FathomMeetingAdapter — renders raw Fathom data into the formats Donna stores.

The raw dict given to the adapter has the shape::

    {
        "meeting":    <client.get_meeting() response>,
        "transcript": <client.get_transcript() response>,
    }

The adapter exposes the unified BaseAdapter surface so the same raw payload
can be rendered as JSON (what we save to default_storage), metadata (what we
land on DeliveryPackage), markdown (future: chat Document), or plain text
(future: agent memory).

Fathom's exact response shape varies by API version. Field accesses use
``.get(...)`` with safe fallbacks so an upstream field rename produces an
empty value rather than a crash; the worst case is a `DeliveryPackage` row
with an empty title, which is still queryable and visible.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from donna.core.integrations import BaseAdapter


class FathomMeetingAdapter(BaseAdapter):
    """Adapter for one Fathom meeting (metadata + transcript)."""

    # ── Convenience accessors ───────────────────────────────────────────────
    @property
    def _meeting(self) -> dict[str, Any]:
        return self.raw.get("meeting") or {}

    @property
    def _transcript(self) -> dict[str, Any]:
        return self.raw.get("transcript") or {}

    # ── BaseAdapter — required ──────────────────────────────────────────────
    def external_id(self) -> str:
        meeting_id = self._meeting.get("id") or self._meeting.get("meeting_id")
        if not meeting_id:
            raise ValueError("Fathom meeting payload missing 'id'/'meeting_id'")
        return str(meeting_id)

    def title(self) -> str:
        return (
            self._meeting.get("title")
            or self._meeting.get("name")
            or "Untitled meeting"
        )

    def occurred_at(self) -> datetime:
        raw = (
            self._meeting.get("recorded_at")
            or self._meeting.get("meeting_date")
            or self._meeting.get("started_at")
            or self._meeting.get("scheduled_start_time")
        )
        if not raw:
            return datetime.now(tz=timezone.utc)
        # Accept both ISO 8601 strings and (rarely) epoch seconds.
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))

    def to_json(self) -> dict:
        """Return the raw structured payload — what we land in storage."""
        return {
            "meeting":    self._meeting,
            "transcript": self._transcript,
        }

    # ── BaseAdapter — optional overrides ────────────────────────────────────
    def metadata(self) -> dict:
        """Provider-specific normalized fields surfaced on DeliveryPackage."""
        m = self._meeting
        return {
            "share_url":        m.get("share_url"),
            "duration_seconds": m.get("duration_seconds") or m.get("duration"),
            "participants":     [
                p.get("email") or p.get("name")
                for p in (m.get("participants") or [])
                if isinstance(p, dict)
            ],
            "host":             (m.get("host") or {}).get("email"),
            "language":         m.get("language"),
        }

    def to_text(self) -> str:
        """Concatenated transcript text — useful for agent memory / search."""
        segments = self._transcript.get("segments") or self._transcript.get("entries") or []
        if not segments:
            # Some shapes carry the transcript as a single string field.
            return self._transcript.get("text") or self._transcript.get("body") or ""

        lines: list[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            speaker = segment.get("speaker") or segment.get("speaker_name") or "Unknown"
            text = segment.get("text") or segment.get("transcript") or ""
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Render as Markdown — future: chat Document body."""
        m = self._meeting
        meta = self.metadata()
        header = [
            f"# {self.title()}",
            "",
            f"**Date:** {self.occurred_at().isoformat()}  ",
        ]
        if meta.get("duration_seconds"):
            header.append(f"**Duration:** {meta['duration_seconds']}s  ")
        if meta.get("participants"):
            header.append(f"**Participants:** {', '.join(meta['participants'])}  ")
        if meta.get("share_url"):
            header.append(f"**Recording:** {meta['share_url']}  ")
        header.append("")
        header.append("## Transcript")
        header.append("")
        header.append(self.to_text() or "_No transcript available._")
        return "\n".join(header)
