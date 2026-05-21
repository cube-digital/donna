"""
DriveClient — HTTP client for Google Drive v3 REST API.

Wraps the endpoints we need for v1 ingestion + picker UX:

- ``list_children``         — folder browse (custom picker)
- ``list_shared_drives``    — Shared Drives picker
- ``get_file``              — file metadata
- ``export_file``           — Google-native export (Docs → text/plain, …)
- ``download_file_media``   — raw bytes for binary files (PDFs, Office)
- ``get_changes_start_token`` / ``iter_changes`` — incremental sync
- ``iter_folder_descendants`` — recursive enumeration for SUBSCRIPTIONS mode

Reference:
    https://developers.google.com/drive/api/v3/reference

`drive.file` scope unlocks ``files.get`` only for files the app has been
granted access to (via Picker or app-created). `drive.readonly` unlocks
the full set of endpoints below.
"""
from __future__ import annotations

import logging
from typing import Iterator

import httpx

from ..client import BaseGoogleClient


logger = logging.getLogger(__name__)


# Default field set for ``files.get`` / ``files.list``. ``*`` is allowed
# but Google recommends explicit field projection for cost.
_FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,createdTime,parents,driveId,"
    "owners(emailAddress,displayName),webViewLink,trashed,starred,md5Checksum"
)


class DriveClient(BaseGoogleClient):
    """Google Drive v3 client. Bind to a user-scoped ``OAuthToken``."""

    base_url = "https://www.googleapis.com/drive/v3"

    # ── Picker — folder browse (needs drive.readonly) ──────────────────────
    def list_children(
        self,
        parent: str = "root",
        drive_id: str | None = None,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> dict:
        """List immediate children of a folder (or 'root')."""
        params: dict[str, object] = {
            "q":         f"'{parent}' in parents and trashed = false",
            "fields":    f"nextPageToken, files({_FILE_FIELDS})",
            "pageSize":  page_size,
        }
        if drive_id:
            params.update(
                {
                    "driveId":            drive_id,
                    "corpora":            "drive",
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives":  "true",
                }
            )
        else:
            params.update(
                {
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives":         "true",
                }
            )
        if page_token:
            params["pageToken"] = page_token
        return self.get("/files", params=params)

    def list_shared_drives(self, page_token: str | None = None) -> dict:
        """List Shared Drives the user has access to (needs drive.readonly)."""
        params: dict[str, object] = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        return self.get("/drives", params=params)

    # ── File metadata + content ────────────────────────────────────────────
    def get_file(self, file_id: str) -> dict:
        return self.get(
            f"/files/{file_id}",
            params={"fields": _FILE_FIELDS, "supportsAllDrives": "true"},
        )

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """Export a Google-native file to ``mime_type``. Returns raw bytes."""
        url = f"{self.base_url}/files/{file_id}/export"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                url,
                params={"mimeType": mime_type},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.content

    def download_file_media(self, file_id: str) -> bytes:
        """``files.get?alt=media`` — raw bytes (PDFs, Office files)."""
        url = f"{self.base_url}/files/{file_id}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                url,
                params={"alt": "media", "supportsAllDrives": "true"},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.content

    # ── Changes API (needs drive.readonly for whole-drive scope) ───────────
    def get_changes_start_token(self) -> str:
        resp = self.get(
            "/changes/startPageToken",
            params={"supportsAllDrives": "true"},
        )
        return resp["startPageToken"]

    def iter_changes(
        self,
        page_token: str,
        include_corpora: str = "user",
    ) -> Iterator[dict]:
        """
        Iterate change entries from ``page_token`` forward.

        ``include_corpora``: ``user`` (My Drive only) or ``allDrives``
        (My Drive + Shared Drives).
        """
        token = page_token
        while True:
            params: dict[str, object] = {
                "pageToken":          token,
                "fields":             f"nextPageToken, newStartPageToken, changes(fileId, removed, time, file({_FILE_FIELDS}))",
                "supportsAllDrives":  "true",
                "includeItemsFromAllDrives": "true",
                "pageSize":           100,
            }
            if include_corpora == "allDrives":
                params["includeRemoved"] = "true"
                params["spaces"] = "drive"
            page = self.get("/changes", params=params)
            for change in page.get("changes") or []:
                yield change
            next_token = page.get("nextPageToken")
            if next_token:
                token = next_token
                continue
            # No more pages — newStartPageToken is the resume token for
            # next sync; expose via last_change_token attribute.
            self.last_change_token = page.get("newStartPageToken") or token
            return

    # ── Folder descendants (SUBSCRIPTIONS mode) ────────────────────────────
    def iter_folder_descendants(
        self,
        folder_id: str,
        recursive: bool = True,
    ) -> Iterator[str]:
        """Yield file IDs under ``folder_id``. Walks subfolders iff recursive."""
        queue: list[str] = [folder_id]
        seen: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            page_token: str | None = None
            while True:
                page = self.list_children(parent=current, page_token=page_token)
                for f in page.get("files") or []:
                    fid = f.get("id")
                    if not fid:
                        continue
                    if f.get("mimeType") == "application/vnd.google-apps.folder":
                        if recursive:
                            queue.append(fid)
                        continue
                    yield fid
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
