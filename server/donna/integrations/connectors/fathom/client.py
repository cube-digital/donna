"""
Fathom HTTP client.

Wraps Fathom's external API:
- ``/meetings`` (LIST only — no singular endpoint exists; meeting metadata
  is sourced from list items or from inbound webhook payloads)
- ``/recordings/{recording_id}/transcript`` (sync return when no destination_url)
- ``/recordings/{recording_id}/summary``    (sync return when no destination_url)
- ``/webhooks`` (CRUD)

Inherits auth header injection, retries, and JSON handling from BaseHTTPClient.
"""
from __future__ import annotations

from typing import Iterator

from donna.core.integrations import BaseHTTPClient


class FathomClient(BaseHTTPClient):
    """Thin wrapper over the Fathom external API."""

    #: Production base URL. The OAuth endpoints live on fathom.video but the
    #: REST API is served from api.fathom.ai (per developers.fathom.ai docs).
    base_url = "https://api.fathom.ai/external/v1"

    # ── Meetings ────────────────────────────────────────────────────────────
    def list_meetings(
        self,
        *,
        cursor: str | None = None,
        include_transcript: bool = False,
        include_summary: bool = False,
        include_action_items: bool = False,
    ) -> dict:
        """One page of ``GET /meetings``: ``{limit, next_cursor, items: [...]}``."""
        params: dict = {
            "include_transcript":   str(include_transcript).lower(),
            "include_summary":      str(include_summary).lower(),
            "include_action_items": str(include_action_items).lower(),
        }
        if cursor:
            params["cursor"] = cursor
        return self.get("/meetings", params=params)

    def iter_meetings(self, **kwargs) -> Iterator[dict]:
        """Yield every meeting across pages."""
        cursor: str | None = None
        while True:
            page = self.list_meetings(cursor=cursor, **kwargs)
            for item in page.get("items", []):
                yield item
            cursor = page.get("next_cursor")
            if not cursor:
                return

    # ── Recording-scoped fetches ────────────────────────────────────────────
    def get_transcript(self, recording_id: str | int) -> dict:
        """Fetch the transcript for a recording (sync return)."""
        return self.get(f"/recordings/{recording_id}/transcript")

    def get_summary(self, recording_id: str | int) -> dict:
        """Fetch the summary for a recording (sync return)."""
        return self.get(f"/recordings/{recording_id}/summary")

    # ── Webhook management ──────────────────────────────────────────────────
    def create_webhook(
        self,
        *,
        destination_url: str,
        triggered_for: list[str],
        include_transcript: bool = True,
        include_summary: bool = True,
        include_action_items: bool = True,
        include_crm_matches: bool = False,
    ) -> dict:
        """
        Register a webhook for the OAuth user backing this client.

        Returns the created webhook payload including ``id`` (used for the
        eventual DELETE) and ``secret`` (HMAC secret unique to this webhook;
        store on Connection.state and pass to BaseWebhookHandler.verify).

        Docs: https://developers.fathom.ai/api-reference/webhooks/create-a-webhook
        """
        return self.post(
            "/webhooks",
            json={
                "destination_url":      destination_url,
                "triggered_for":        triggered_for,
                "include_transcript":   include_transcript,
                "include_summary":      include_summary,
                "include_action_items": include_action_items,
                "include_crm_matches":  include_crm_matches,
            },
        )

    def delete_webhook(self, webhook_id: str) -> None:
        """
        Delete a registered webhook by id. 204 on success. Callers should
        tolerate 404 (already gone) — see FathomProvider.on_disconnect.
        """
        self.delete(f"/webhooks/{webhook_id}")
