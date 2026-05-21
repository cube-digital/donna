"""
DriveProvider — Google Drive connector.

Shares OAuth (vendor slug ``google``) with Gmail. Initial scope on first
pair is ``drive.file`` only — clean consent for casual users. Folder
watching + ``mode=everything`` need ``drive.readonly`` and are unlocked
via the scope-upgrade endpoint
(``POST /api/v1/integrations/drive/subscription/upgrade-scope``).

See plans/08b-google-drive-integration.md for the design contract.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from donna.core.integrations import (
    BaseWebhookHandler,
    register,
    validate_against_schema,
)
from donna.core.integrations.exceptions import (
    IntegrationError,
)

from ..oauth import GoogleOAuthHandler
from .adapter import DriveFileAdapter
from .client import DriveClient

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider, OAuthToken
    from donna.integrations.models import Connection
    from donna.workspaces.models import Workspace


# Scope required to enable folder subscriptions + ``mode=everything``.
_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


_DRIVE_CONFIG_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type":    "object",
    "required": ["mode"],
    "properties": {
        "mode": {"enum": ["everything", "subscriptions"]},
        "files": {
            "type":  "array",
            "items": {"type": "string", "maxLength": 64},
        },
        "folders": {
            "type":  "array",
            "items": {
                "type": "object",
                "required": ["id", "recursive"],
                "properties": {
                    "id":        {"type": "string", "maxLength": 64},
                    "name":      {"type": "string", "maxLength": 255},
                    "recursive": {"type": "boolean"},
                    "drive_id":  {"type": ["string", "null"], "maxLength": 64},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


@register
class DriveProvider:
    """Connector for Google Drive — read-only file ingest in v1."""

    # ── Identity ────────────────────────────────────────────────────────────
    slug = "drive"
    display_name = "Google Drive"
    category = "documents"

    # ── OAuth coupling ──────────────────────────────────────────────────────
    oauth_provider_slug = "google"
    token_scope = "user"

    # ── Static OAuth defaults (consumed by integrations_bootstrap) ─────────
    default_authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    default_token_url = "https://oauth2.googleapis.com/token"
    # Initial scope is ``drive.file`` only — Picker-friendly, clean consent.
    # ``drive.readonly`` is granted later by the scope-upgrade endpoint.
    default_scopes: list[str] = [
        "https://www.googleapis.com/auth/drive.file",
    ]

    # ── Capabilities ────────────────────────────────────────────────────────
    # v1 polls via Celery beat. Watch + Pub/Sub push notifications deferred.
    supports_webhooks = False

    # ── Per-Connection config contract ─────────────────────────────────────
    config_schema: dict = _DRIVE_CONFIG_SCHEMA
    default_config: dict = {
        "mode":    "subscriptions",
        "files":   [],
        "folders": [],
    }

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> DriveClient:
        return DriveClient(token=token)

    def oauth_handler(self, oauth_provider: "OAuthProvider") -> GoogleOAuthHandler:
        return GoogleOAuthHandler(config=oauth_provider)

    def webhook_handler(self) -> BaseWebhookHandler:  # pragma: no cover
        raise NotImplementedError(
            "DriveProvider has no webhook handler in v1 (poll-based). "
            "Watch + Pub/Sub deferred."
        )

    def adapter_for(self, raw: dict) -> DriveFileAdapter:
        return DriveFileAdapter(raw=raw)

    # ── Webhook / workspace resolution (stubbed for v1) ────────────────────
    def resolve_workspace(self, parsed: dict) -> "Workspace":  # pragma: no cover
        raise NotImplementedError(
            "Drive uses scheduled polling per Connection; resolve_workspace "
            "is unused until Watch+Pub/Sub lands."
        )

    def dispatch_webhook(self, *, parsed: dict, workspace: "Workspace") -> None:  # pragma: no cover
        raise IntegrationError(
            "DriveProvider does not accept webhooks in v1; sync is poll-driven."
        )

    # ── Per-Connection config hooks ─────────────────────────────────────────
    def validate_config(
        self, config: dict, *, connection: "Connection | None" = None
    ) -> dict:
        """
        Validate the user-submitted config blob. Cross-field rule:
        ``mode=everything`` and any folder subscriptions require the
        backing OAuthToken to hold ``drive.readonly`` scope.
        """
        validate_against_schema(config, self.config_schema)

        needs_readonly = (
            config.get("mode") == "everything"
            or bool(config.get("folders"))
        )
        if needs_readonly and connection is not None:
            token = connection.token
            scopes = set((token.scope or "").split())
            if _DRIVE_READONLY_SCOPE not in scopes:
                raise ValueError(
                    "Folder watching and mode=everything require drive.readonly. "
                    "Upgrade via POST /api/v1/integrations/drive/subscription/upgrade-scope."
                )
        return config

    # ── Progressive scope upgrade ──────────────────────────────────────────
    def build_scope_upgrade_url(
        self,
        *,
        connection: "Connection",
        redirect_to: str | None = None,
    ) -> str:
        """
        Construct an OAuth authorize URL that requests ``drive.readonly``
        on top of the vendor's default scopes. Used to unlock folder
        watching + ``mode=everything`` after the user has already
        completed the initial ``drive.file``-only pair.

        The callback uses the standard ``/oauth/callback`` flow — token
        scopes get merged via ``include_granted_scopes=true``.
        """
        from donna.authentication.models import OAuthProvider

        oauth_config = OAuthProvider.objects.get(slug=self.oauth_provider_slug)
        handler = self.oauth_handler(oauth_config)

        # State payload mirrors RegistryService.initiate_connect — same
        # callback verifies and upserts the OAuthToken.
        state_payload = {
            "user_id":      str(connection.user_id) if connection.user_id else "",
            "workspace_id": str(connection.workspace_id),
            "slug":         self.slug,
            "redirect_to":  redirect_to or "",
        }
        return handler.build_authorize_url(
            state_payload=state_payload,
            extra_scopes=[_DRIVE_READONLY_SCOPE],
        )

    def picker(self, resource: str, params: dict, *, connection: "Connection") -> dict:
        """
        Picker resources:

        - ``drives`` — list Shared Drives (needs drive.readonly).
        - ``browse`` — folder browser. Query params: ``parent`` (folder ID
          or ``"root"``), ``drive_id`` (Shared Drive ID, optional),
          ``page_token``.
        """
        with self.client(connection.token) as client:
            if resource == "drives":
                resp = client.list_shared_drives()
                return {
                    "drives": [
                        {"id": d.get("id"), "name": d.get("name")}
                        for d in (resp.get("drives") or [])
                    ],
                }

            if resource == "browse":
                parent = params.get("parent") or "root"
                drive_id = params.get("drive_id") or None
                page_token = params.get("page_token") or None
                resp = client.list_children(
                    parent=parent,
                    drive_id=drive_id,
                    page_token=page_token,
                )
                items = []
                for f in (resp.get("files") or []):
                    mime = f.get("mimeType", "")
                    items.append(
                        {
                            "id":         f.get("id"),
                            "name":       f.get("name"),
                            "mime_type":  mime,
                            "is_folder":  mime == "application/vnd.google-apps.folder",
                            "modified":   f.get("modifiedTime"),
                        }
                    )
                return {
                    "items":           items,
                    "next_page_token": resp.get("nextPageToken"),
                }

        raise ValueError(f"Drive picker has no resource {resource!r}")
