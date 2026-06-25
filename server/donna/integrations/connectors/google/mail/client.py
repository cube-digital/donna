"""
GmailClient — HTTP client for Gmail v1 REST API.

Wraps the endpoints we need for v1 ingestion:

- ``list_messages``  — list+filter (used by cold-start sync)
- ``get_message``    — full message payload (used by per-message ingest)
- ``history``        — incremental sync from a stored ``historyId``
- ``get_profile``    — ``users.getProfile`` (used for the workspace
                       resolution fallback + future external_account_id)

Reference:
    https://developers.google.com/gmail/api/reference/rest
"""
from __future__ import annotations

from typing import Iterator

from ..client import BaseGoogleClient


class GmailClient(BaseGoogleClient):
    """Gmail v1 client. Bind to a user-scoped ``OAuthToken``."""

    base_url = "https://gmail.googleapis.com/gmail/v1"

    # ── Messages ────────────────────────────────────────────────────────────
    def list_messages(
        self,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 100,
        label_ids: list[str] | None = None,
        include_spam_trash: bool = False,
    ) -> dict:
        """List message IDs for the authenticated user. Paginated."""
        params: dict[str, object] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        if label_ids:
            params["labelIds"] = label_ids
        if include_spam_trash:
            params["includeSpamTrash"] = "true"
        return self.get("/users/me/messages", params=params)

    def iter_all_messages(
        self,
        query: str | None = None,
        max_results: int = 100,
        label_ids: list[str] | None = None,
    ) -> Iterator[dict]:
        """Iterate every message id matching the query, walking page tokens."""
        page_token: str | None = None
        while True:
            page = self.list_messages(
                query=query,
                page_token=page_token,
                max_results=max_results,
                label_ids=label_ids,
            )
            for item in page.get("messages", []) or []:
                yield item
            page_token = page.get("nextPageToken")
            if not page_token:
                return

    def get_message(self, message_id: str, fmt: str = "full") -> dict:
        """Return the full Gmail message (payload, headers, parts)."""
        return self.get(
            f"/users/me/messages/{message_id}",
            params={"format": fmt},
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> dict:
        """Fetch one attachment by id.

        Returns ``{"size": int, "data": "<base64url>"}``. Large
        attachments aren't inlined on ``messages.get(format=full)``;
        the part carries ``body.attachmentId`` and callers fetch
        bytes here.
        """
        return self.get(
            f"/users/me/messages/{message_id}/attachments/{attachment_id}",
        )

    # ── History (incremental sync) ──────────────────────────────────────────
    def history(
        self,
        start_history_id: str,
        page_token: str | None = None,
        history_types: list[str] | None = None,
        label_id: str | None = None,
    ) -> dict:
        """List historical changes since ``startHistoryId``."""
        params: dict[str, object] = {"startHistoryId": start_history_id}
        if page_token:
            params["pageToken"] = page_token
        if history_types:
            params["historyTypes"] = history_types
        if label_id:
            params["labelId"] = label_id
        return self.get("/users/me/history", params=params)

    def iter_history_messages(
        self,
        start_history_id: str,
        history_types: list[str] | None = None,
    ) -> Iterator[tuple[str, str]]:
        """
        Yield ``(change_type, message_id)`` across every history page.

        Change types include ``messagesAdded``, ``messagesDeleted``,
        ``labelsAdded``, ``labelsRemoved``.
        """
        page_token: str | None = None
        types = history_types or ["messageAdded"]
        while True:
            page = self.history(
                start_history_id=start_history_id,
                page_token=page_token,
                history_types=types,
            )
            for entry in page.get("history", []) or []:
                for change_type in (
                    "messagesAdded",
                    "messagesDeleted",
                    "labelsAdded",
                    "labelsRemoved",
                ):
                    for sub in entry.get(change_type, []) or []:
                        msg = sub.get("message") or {}
                        if msg.get("id"):
                            yield change_type, msg["id"]
            page_token = page.get("nextPageToken")
            if not page_token:
                return

    # ── Labels ──────────────────────────────────────────────────────────────
    def list_labels(self) -> dict:
        """``users.labels.list`` — returns ``{labels: [{id, name, type, ...}, ...]}``.

        Used by the picker endpoint to populate the subscription config UI.
        """
        return self.get("/users/me/labels")

    # ── Profile (for workspace resolution + account identity) ───────────────
    def get_profile(self) -> dict:
        """``users.getProfile`` → ``emailAddress``, ``messagesTotal``,
        ``threadsTotal``, ``historyId``."""
        return self.get("/users/me/profile")
