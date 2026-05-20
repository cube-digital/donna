"""
FathomProvider — the connector class for Fathom (meeting transcripts).

Single-product vendor → flat layout: 4 files in this folder
(provider, client, adapter, tasks). Uses framework defaults for webhook
verification and OAuth.

Registered at startup by ``donna.integrations.apps.IntegrationsConfig.ready()``
via recursive discovery (see Task 8).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from donna.core.integrations import (
    BaseOAuthHandler,
    BaseWebhookHandler,
    register,
)
from donna.core.integrations.exceptions import WorkspaceResolutionFailed

from .adapter import FathomMeetingAdapter
from .client import FathomClient

if TYPE_CHECKING:
    from donna.authentication.models import OAuthProvider, OAuthToken
    from donna.workspaces.models import Workspace


@register
class FathomProvider:
    """Connector for Fathom.video — pulls meeting metadata + transcripts."""

    # ── Identity ────────────────────────────────────────────────────────────
    slug = "fathom"
    display_name = "Fathom"
    category = "meeting_transcripts"

    # ── OAuth coupling ──────────────────────────────────────────────────────
    oauth_provider_slug = "fathom"
    token_scope = "user"

    # ── Static OAuth defaults (consumed by integrations_bootstrap) ─────────
    default_authorize_url = "https://fathom.video/oauth/authorize"
    default_token_url = "https://fathom.video/oauth/token"
    default_scopes: list[str] = ["transcripts:read", "meetings:read"]

    # ── Capabilities ────────────────────────────────────────────────────────
    supports_webhooks = True

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> FathomClient:
        return FathomClient(token=token)

    def webhook_handler(self) -> BaseWebhookHandler:
        # Fathom uses the framework default — HMAC-SHA256 in the configured
        # header. The exact header name is set on the OAuthProvider row
        # (override via metadata if needed).
        return BaseWebhookHandler(config=self._oauth_config())

    def oauth_handler(self, oauth_provider: "OAuthProvider") -> BaseOAuthHandler:
        return BaseOAuthHandler(config=oauth_provider)

    def adapter_for(self, raw: dict) -> FathomMeetingAdapter:
        return FathomMeetingAdapter(raw=raw)

    # ── Workspace resolution ────────────────────────────────────────────────
    def resolve_workspace(self, parsed: dict) -> "Workspace":
        """
        Map a parsed Fathom webhook payload to its destination workspace.

        Convention: every Fathom webhook payload carries a recording owner
        (host) identifier. We look up the ``OAuthToken`` belonging to that
        user and resolve the workspace from the token.

        v1 limitation: the lookup matches the Fathom owner identifier against
        the upstream user id stored on the token. ``OAuthToken`` does not yet
        have an ``external_account_id`` column — we plan to add it when the
        first real webhook payload lands. For now, the resolver falls back to
        the single Fathom token in the database (one token = one workspace),
        which is enough for the single-user MVP. The fallback raises clearly
        if it's ambiguous so the gap is visible.
        """
        from donna.authentication.models import OAuthToken

        external_user_id = (
            parsed.get("user_id")
            or parsed.get("fathom_user_id")
            or (parsed.get("user") or {}).get("id")
            or (parsed.get("host") or {}).get("id")
        )

        tokens = OAuthToken.objects.filter(
            provider__slug=self.oauth_provider_slug,
            workspace__isnull=False,
        ).select_related("workspace")

        # MVP fallback — single connected workspace, no per-user resolution.
        # Replace once OAuthToken grows an `external_account_id` column.
        token_list = list(tokens[:2])
        if not token_list:
            raise WorkspaceResolutionFailed(
                "no Fathom OAuthToken exists; cannot resolve workspace "
                f"(external_user_id={external_user_id!r})"
            )
        if len(token_list) > 1:
            raise WorkspaceResolutionFailed(
                "multiple Fathom OAuthTokens exist; resolve_workspace needs "
                "OAuthToken.external_account_id to disambiguate "
                f"(external_user_id={external_user_id!r})"
            )
        return token_list[0].workspace

    # ── Webhook dispatch ────────────────────────────────────────────────────
    def dispatch_webhook(self, *, parsed: dict, workspace: "Workspace") -> None:
        """
        Enqueue the Fathom ingestion task for an incoming meeting-ended event.

        Pulls the meeting id from the parsed payload using the same fallback
        chain as ``resolve_workspace`` (Fathom's webhook payload shape varies
        slightly by event type).
        """
        from .tasks import ingest_fathom_meeting

        meeting_id = (
            parsed.get("meeting_id")
            or (parsed.get("meeting") or {}).get("id")
            or parsed.get("id")
        )
        if not meeting_id:
            raise ValueError(
                "Fathom webhook payload has no recognisable meeting id "
                f"(keys={list(parsed.keys())})"
            )

        ingest_fathom_meeting.delay(str(workspace.id), str(meeting_id))

    # ── Internal ────────────────────────────────────────────────────────────
    def _oauth_config(self) -> "OAuthProvider":
        """Look up the OAuthProvider row backing this connector."""
        from donna.authentication.models import OAuthProvider

        return OAuthProvider.objects.get(slug=self.oauth_provider_slug)
