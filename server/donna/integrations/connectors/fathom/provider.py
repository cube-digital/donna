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

import logging

import httpx
from django.conf import settings
from django.urls import reverse

from donna.core.integrations import (
    BaseOAuthHandler,
    BaseWebhookHandler,
    register,
)
from donna.core.integrations.exceptions import (
    WebhookSignatureInvalid,
    WorkspaceResolutionFailed,
)

from .adapter import FathomMeetingAdapter
from .client import FathomClient

if TYPE_CHECKING:
    from donna.integrations.models import ClientCredentials, Connection, OAuthToken
    from donna.workspaces.models import Workspace


logger = logging.getLogger(__name__)


class FathomWebhookHandler(BaseWebhookHandler):
    """
    Fathom-specific webhook handler.

    Fathom issues a unique HMAC secret **per webhook registration** (returned
    by ``POST /webhooks`` and persisted on ``Connection.state["webhook"]
    ["secret"]``), so verification cannot read from the global
    ``ClientCredentials.webhook_secret``. We override ``verify`` to read the
    secret from the resolved Connection threaded in by the view.
    """

    # TODO: confirm exact header name from a real Fathom webhook delivery.
    # Fathom's docs do not pin this in OpenAPI; revisit once the first signed
    # payload arrives in dev.
    signature_header: str = "X-Fathom-Signature"

    def verify(
        self,
        payload: bytes,
        signature: str | None,
        *,
        connection: "Connection | None" = None,
    ) -> bool:
        import hashlib
        import hmac

        if not signature:
            raise WebhookSignatureInvalid("missing signature header")
        if connection is None:
            raise WebhookSignatureInvalid(
                "Fathom webhook verification requires a resolved Connection"
            )

        webhook_state = (connection.state or {}).get("webhook") or {}
        secret = webhook_state.get("secret") or ""
        if not secret:
            raise WebhookSignatureInvalid(
                f"no per-Connection webhook secret on Connection(id={connection.id})"
            )

        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookSignatureInvalid("signature does not match payload")
        return True


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
    default_authorize_url = "https://fathom.video/external/v1/oauth2/authorize"
    default_token_url = "https://fathom.video/external/v1/oauth2/token"
    default_scopes: list[str] = ["public_api"]

    # ── Capabilities ────────────────────────────────────────────────────────
    supports_webhooks = True

    # ── Factory methods ─────────────────────────────────────────────────────
    def client(self, token: "OAuthToken") -> FathomClient:
        return FathomClient(token=token)

    def webhook_handler(self) -> BaseWebhookHandler:
        # Fathom issues a unique HMAC secret per webhook registration; the
        # custom handler reads that secret from the resolved Connection.state
        # rather than the shared ClientCredentials.webhook_secret.
        return FathomWebhookHandler(config=self._oauth_config())

    def oauth_handler(self, oauth_provider: "ClientCredentials") -> BaseOAuthHandler:
        return BaseOAuthHandler(config=oauth_provider, connector_cls=type(self))

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
        from donna.integrations.models import OAuthToken

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

        # Per "New meeting content ready" webhook docs the payload itself is
        # the meeting block — the recording id is the stable key.
        meeting = parsed.get("meeting") if isinstance(parsed.get("meeting"), dict) else parsed
        recording_id = (
            meeting.get("recording_id")
            or parsed.get("recording_id")
            or parsed.get("meeting_id")
            or parsed.get("id")
        )
        if not recording_id:
            raise ValueError(
                "Fathom webhook payload has no recognisable recording id "
                f"(keys={list(parsed.keys())})"
            )

        ingest_fathom_meeting.delay(str(workspace.id), str(recording_id), meeting)

    # ── Connection lifecycle ────────────────────────────────────────────────
    def on_connect(self, *, token: "OAuthToken", connection: "Connection") -> None:
        """
        Register a Fathom webhook for the just-connected user account.

        Stores ``{id, secret}`` on ``Connection.state["webhook"]`` for use by
        ``FathomWebhookHandler.verify`` and ``on_disconnect``. Raising here
        rolls back the OAuthToken + Connection rows in the surrounding
        ``RegistryService.handle_callback`` transaction.
        """
        destination_url = self._webhook_destination_url()
        try:
            resp = self.client(token).create_webhook(
                destination_url=destination_url,
                # Default selection — ship only what the user explicitly owns.
                # Make user-tunable via Connection.config in a follow-up.
                triggered_for=["my_recordings", "my_shared_with_team_recordings"],
            )
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text
            except Exception:  # noqa: BLE001
                pass
            logger.error(
                "fathom_create_webhook_failed",
                extra={
                    "status":          exc.response.status_code,
                    "destination_url": destination_url,
                    "body":            body[:500],
                },
            )
            # Re-raise so RegistryService.handle_callback's @transaction.atomic
            # rolls back the OAuthToken + Connection — never leave a half-
            # configured binding (token saved, no webhook registered).
            raise

        state = dict(connection.state or {})
        state["webhook"] = {"id": resp["id"], "secret": resp["secret"]}
        connection.state = state
        connection.save(update_fields=["state", "updated_at"])

        # Backfill existing meetings — the webhook above is CDC (delivers only
        # meetings recorded AFTER connect). Fire once the surrounding
        # handle_callback transaction commits so the worker sees the Connection
        # row (and so a later rollback doesn't leave a spurious backfill queued).
        from django.db import transaction

        from .tasks import backfill_fathom_meetings

        workspace_id = str(connection.workspace_id)
        transaction.on_commit(
            lambda: backfill_fathom_meetings.delay(workspace_id),
        )

        logger.info(
            "fathom_webhook_registered",
            extra={
                "connection_id": str(connection.id),
                "webhook_id":    resp["id"],
                "destination":   destination_url,
            },
        )

    def on_disconnect(self, *, token: "OAuthToken", connection: "Connection") -> None:
        """
        Delete the Fathom webhook registered at on_connect, if any. Tolerates
        404 (already gone). Any other error propagates and is logged + swallowed
        by RegistryService.disconnect so local cleanup proceeds.
        """
        webhook_state = (connection.state or {}).get("webhook") or {}
        webhook_id = webhook_state.get("id")
        if not webhook_id:
            return

        try:
            self.client(token).delete_webhook(webhook_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.info(
                    "fathom_webhook_already_deleted",
                    extra={"connection_id": str(connection.id), "webhook_id": webhook_id},
                )
                return
            raise

    # ── Internal ────────────────────────────────────────────────────────────
    def _webhook_destination_url(self) -> str:
        """
        Absolute, publicly reachable URL for ``ProviderWebhookView`` (Fathom
        slug). Composed from ``settings.DONNA_PUBLIC_BASE_URL`` + the named
        URL route. In dev this must point at a tunnel (ngrok / cloudflared);
        Fathom cannot reach ``localhost``.
        """
        base = settings.DONNA_PUBLIC_BASE_URL.rstrip("/")
        path = reverse("integration-webhook-callback", kwargs={"slug": self.slug})
        return f"{base}{path}"

    def _oauth_config(self) -> "ClientCredentials":
        """
        Return the deployment-wide ClientCredentials row.

        Webhook verification has no workspace context at request time, so
        ``webhook_secret`` must live on the global row (``workspace=NULL``).
        Workspace-scoped rows can carry per-workspace ``client_id`` /
        ``client_secret`` for the OAuth flow but never the webhook secret.
        """
        from donna.integrations.models import ClientCredentials

        return ClientCredentials.objects.get(
            slug=self.oauth_provider_slug,
            workspace__isnull=True,
        )
