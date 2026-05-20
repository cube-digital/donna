"""
Fathom HTTP client.

Wraps Fathom's external API: get meeting metadata and transcripts.
Inherits auth header injection, retries, and JSON handling from BaseHTTPClient.
"""
from __future__ import annotations

from donna.core.integrations import BaseHTTPClient


class FathomClient(BaseHTTPClient):
    """Thin wrapper over the Fathom external API."""

    #: Production base URL. Override via subclass for testing if needed.
    base_url = "https://api.fathom.video/external/v1"

    # ── Meeting metadata ────────────────────────────────────────────────────
    def get_meeting(self, meeting_id: str) -> dict:
        """
        Fetch the metadata for a meeting: participants, duration, recorded_at,
        share_url, etc.
        """
        return self.get(f"/meetings/{meeting_id}")

    # ── Transcript ──────────────────────────────────────────────────────────
    def get_transcript(self, meeting_id: str) -> dict:
        """
        Fetch the full transcript for a meeting. Shape is provider-defined;
        the adapter normalizes it before storage.
        """
        return self.get(f"/meetings/{meeting_id}/transcript")
