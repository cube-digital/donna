"""
DriveFileAdapter — renders a Drive ``files.get`` response to Donna's
adapter surface.

Raw shape::

    raw = {
        "file":             {<files.get response>},
        "exported_text":    "<optional plain-text export>",
    }

``files.get`` includes metadata only. The ingest task fills
``exported_text`` after calling ``files.export`` for Google-native types
(Docs/Sheets/Slides). For binary files (PDFs, Office, media) ``to_text``
returns empty in v1; the raw bytes live separately in ``default_storage``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from donna.core.integrations import BaseEntityAdapter


# mimeType → export format. Used by the ingest task; lives here so the
# adapter and task agree on what gets extracted.
GOOGLE_EXPORT_MIMES = {
    "application/vnd.google-apps.document":     "text/plain",
    "application/vnd.google-apps.spreadsheet":  "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# mimeType → binary download (no export). v1 stores bytes; extraction deferred.
BINARY_MIMES = {
    "application/pdf",
}


class DriveFileAdapter(BaseEntityAdapter):
    """Adapter for one Drive file (metadata + optional exported text).

    Phase 2 (2026-06-15): emits ``CanonicalEntity(entity_type="doc")``.
    Required DocExtensions nav: ``doc_type`` — defaults to "other";
    the cortex pipeline's tier-A heuristic classifier upgrades it
    when filename / MIME / body anchors match a known type.
    """

    canonical_type = "doc"

    @property
    def _file(self) -> dict[str, Any]:
        return self.raw.get("file") or {}

    # ── BaseAdapter — required ─────────────────────────────────────────────
    def external_id(self) -> str:
        fid = self._file.get("id")
        if not fid:
            raise ValueError("Drive file payload missing 'id'")
        return str(fid)

    def title(self) -> str:
        return self._file.get("name") or "(untitled)"

    def occurred_at(self) -> datetime:
        # Prefer modifiedTime; fall back to createdTime; final fallback now.
        for key in ("modifiedTime", "createdTime"):
            value = self._file.get(key)
            if not value:
                continue
            try:
                # RFC3339 — fromisoformat handles 'Z' suffix in 3.11+.
                if value.endswith("Z"):
                    value = value.replace("Z", "+00:00")
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                try:
                    return parsedate_to_datetime(value)
                except (TypeError, ValueError):
                    continue
        return datetime.now(tz=timezone.utc)

    def to_json(self) -> dict:
        return self._file

    # ── Optional ───────────────────────────────────────────────────────────
    def to_text(self) -> str:
        return self.raw.get("exported_text") or ""

    def to_markdown(self) -> str:
        f = self._file
        lines = [
            f"# {self.title()}",
            "",
            f"**MIME:** `{f.get('mimeType', 'unknown')}`  ",
        ]
        owners = ", ".join(
            o.get("emailAddress", "") for o in (f.get("owners") or [])
        )
        if owners:
            lines.append(f"**Owners:** {owners}  ")
        if f.get("webViewLink"):
            lines.append(f"**Open:** {f['webViewLink']}  ")
        lines.append(f"**Modified:** {self.occurred_at().isoformat()}  ")
        lines.append("")
        body = self.to_text() or "_(no plain-text export available)_"
        lines.append(body)
        return "\n".join(lines)

    def metadata(self) -> dict:
        f = self._file
        return {
            "mime_type":      f.get("mimeType"),
            "size":           f.get("size"),
            "owners":         [o.get("emailAddress") for o in (f.get("owners") or [])],
            "modified_time":  f.get("modifiedTime"),
            "created_time":   f.get("createdTime"),
            "parents":        f.get("parents") or [],
            "drive_id":       f.get("driveId"),
            "web_view_link":  f.get("webViewLink"),
            "trashed":        f.get("trashed", False),
            "starred":        f.get("starred", False),
            "md5_checksum":   f.get("md5Checksum"),
            "has_export":     f.get("mimeType") in GOOGLE_EXPORT_MIMES,
            "has_binary":     f.get("mimeType") in BINARY_MIMES,
        }

    # ── BaseEntityAdapter — canonical extensions ────────────────────────────
    def _extensions(self) -> dict:
        """DocExtensions-shaped payload (nav: doc_type).

        ``doc_type`` defaults to "other"; cortex pipeline's tier-A
        heuristic classifier upgrades it when filename / MIME / body
        anchors match a known type (spec, contract, runbook, …).
        """
        f = self._file
        owner_email = None
        owners = f.get("owners") or []
        if owners and isinstance(owners[0], dict):
            owner_email = owners[0].get("emailAddress")

        return {
            "doc_type":     "other",  # tier-A classifier may overwrite
            "mime":         f.get("mimeType"),
            "author_email": owner_email,
            "filename":     f.get("name"),
            "web_view_link": f.get("webViewLink"),
        }
