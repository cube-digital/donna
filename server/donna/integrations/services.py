"""
RegistryService — the only service in the integrations app for v1.

Owns the connect/disconnect/list/callback flow. Bridges between the API
views and the framework primitives in ``donna.core.integrations``.

`IngestionService` is intentionally deferred — the webhook view and the
per-connector Celery tasks call the framework + DB directly. See
plans/03-conventions-and-api.md for the documented exception.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from django.db import transaction

from donna.core.integrations import (
    NotConfigured,
    ProviderNotRegistered,
    all_loaded,
    configured_for_workspace,
    get as get_provider,
)


if TYPE_CHECKING:
    from donna.users.models import User
    from donna.workspaces.models import Workspace

    from .models import ClientCredentials, OAuthToken


logger = logging.getLogger(__name__)


class IntegrationStatus:
    """Lightweight DTO returned by ``RegistryService.list_*``."""

    __slots__ = ("slug", "display_name", "category", "is_configured", "is_connected")

    def __init__(
        self,
        slug: str,
        display_name: str,
        category: str,
        is_configured: bool,
        is_connected: bool,
    ):
        self.slug = slug
        self.display_name = display_name
        self.category = category
        self.is_configured = is_configured
        self.is_connected = is_connected

    def as_dict(self) -> dict:
        return {
            "slug":          self.slug,
            "display_name":  self.display_name,
            "category":      self.category,
            "is_configured": self.is_configured,
            "is_connected":  self.is_connected,
        }


class RegistryService:
    """
    View-facing service for the integration registry + OAuth lifecycle.

    Constructed by ``ServiceMethodMixin`` with ``current_user`` + ``company``
    (workspace) from the request. Methods take the workspace explicitly so
    callers can be specific.
    """

    def __init__(
        self,
        current_user: Optional["User"] = None,
        company: Optional["Workspace"] = None,
    ):
        self.current_user = current_user
        self.company = company

    # ── Listing ─────────────────────────────────────────────────────────────
    def list_for_workspace(self, workspace: "Workspace") -> list[IntegrationStatus]:
        """All connectors visible to the workspace, with connection status."""
        from django.db.models import Q

        from .models import ClientCredentials, Connection

        enabled_slugs = set(
            ClientCredentials.objects
            .filter(is_enabled=True)
            .values_list("slug", flat=True)
        )
        # A connector is "connected" only when it has its own enabled Connection
        # row — NOT merely because a token exists for the shared vendor. Gmail
        # and Drive share oauth_provider_slug="google"; keying on the vendor
        # token flipped BOTH on when only one was actually connected.
        owner = Q(workspace=workspace)
        if self.current_user is not None:
            owner |= Q(user=self.current_user)
        connected_slugs = set(
            Connection.objects
            .filter(enabled=True)
            .filter(owner)
            .values_list("provider_slug", flat=True)
        )

        statuses: list[IntegrationStatus] = []
        for cls in all_loaded():
            statuses.append(
                IntegrationStatus(
                    slug=cls.slug,
                    display_name=cls.display_name,
                    category=cls.category,
                    is_configured=cls.oauth_provider_slug in enabled_slugs,
                    is_connected=cls.slug in connected_slugs,
                )
            )
        return statuses

    def get_status(self, workspace: "Workspace", slug: str) -> IntegrationStatus:
        """Status for one connector. Raises ProviderNotRegistered if unknown."""
        from django.db.models import Q

        from .models import ClientCredentials, Connection

        cls = get_provider(slug)  # raises ProviderNotRegistered

        # Either workspace-specific row OR deployment-wide row counts as configured.
        is_configured = (
            ClientCredentials.objects.resolve(
                cls.oauth_provider_slug, workspace=workspace
            )
            is not None
        )

        # Caller sees a connection if either the workspace has one, or the
        # current user has a personal one.
        owner_clause = Q(workspace=workspace)
        if self.current_user is not None:
            owner_clause |= Q(user=self.current_user)

        # Per-connector Connection row, NOT the shared vendor token — Gmail and
        # Drive share the "google" vendor, so a vendor-token check reported both
        # connected when only one was.
        is_connected = Connection.objects.filter(
            provider_slug=cls.slug,
        ).filter(owner_clause).exists()

        return IntegrationStatus(
            slug=cls.slug,
            display_name=cls.display_name,
            category=cls.category,
            is_configured=is_configured,
            is_connected=is_connected,
        )

    # ── Connect ─────────────────────────────────────────────────────────────
    def initiate_connect(
        self,
        workspace: "Workspace",
        user: "User",
        slug: str,
        redirect_to: str | None = None,
    ) -> str:
        """
        Build the upstream authorize URL. Returns the URL to redirect to.
        """
        from .models import ClientCredentials

        cls = get_provider(slug)
        provider = cls()

        oauth_config = ClientCredentials.objects.resolve(
            cls.oauth_provider_slug, workspace=workspace
        )
        if oauth_config is None:
            raise NotConfigured(
                f"No enabled ClientCredentials({cls.oauth_provider_slug!r}) "
                f"row for workspace={workspace.id} or deployment-wide."
            )

        handler = provider.oauth_handler(oauth_config)
        state_payload = {
            "user_id":              str(user.id),
            "workspace_id":         str(workspace.id),
            "slug":                 slug,
            "redirect_to":          redirect_to or "",
            # Pin the exact ClientCredentials row that signed the authorize
            # URL — callback exchanges the code with the same client_id/secret.
            "client_credentials_id": str(oauth_config.id),
        }
        return handler.build_authorize_url(state_payload=state_payload)

    # ── Disconnect ──────────────────────────────────────────────────────────
    @transaction.atomic
    def disconnect(self, workspace: "Workspace", user: "User", slug: str) -> bool:
        """
        Revoke + delete the OAuthToken for this caller. Returns True when a
        token was removed, False when nothing was connected.
        """
        from .models import ClientCredentials, OAuthToken

        cls = get_provider(slug)
        provider = cls()

        oauth_config = ClientCredentials.objects.resolve(
            cls.oauth_provider_slug, workspace=workspace
        )
        if oauth_config is None:
            return False

        # Match the caller's token — user-scoped first, then workspace-scoped.
        token = (
            OAuthToken.objects
            .filter(provider=oauth_config)
            .filter(user=user)
            .first()
            or OAuthToken.objects
            .filter(provider=oauth_config, workspace=workspace)
            .first()
        )
        if token is None:
            return False

        # Per-connector pre-disconnect cleanup (e.g. delete remote webhook
        # registrations). Runs while the OAuth token is still valid — vendor
        # APIs needed for cleanup will fail after revoke. Failures are logged
        # and swallowed so local state cleanup always completes; an orphaned
        # vendor-side resource is recoverable, a half-deleted DB row is not.
        connection = (
            token.connection_set.filter(provider_slug=slug).first()  # type: ignore[attr-defined]
            if hasattr(token, "connection_set")
            else None
        )
        if connection is not None:
            try:
                on_disconnect = getattr(provider, "on_disconnect", None)
                if on_disconnect is not None:
                    on_disconnect(token=token, connection=connection)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "on_disconnect_failed",
                    extra={"slug": slug, "error": str(exc)},
                )

        # Best-effort revocation; ignore upstream failures.
        try:
            provider.oauth_handler(oauth_config).revoke(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "oauth_revoke_failed_during_disconnect",
                extra={"slug": slug, "error": str(exc)},
            )

        token.delete()
        return True

    # ── OAuth callback ──────────────────────────────────────────────────────
    @transaction.atomic
    def handle_callback(self, slug: str, code: str, state: str) -> "OAuthToken":
        """
        Complete the OAuth dance from a callback view. Verifies state,
        exchanges code, persists the OAuthToken. Returns the new/updated row.

        ``slug`` is the URL slug — i.e. the vendor / ``oauth_provider_slug``
        (e.g. ``"google"``), not the connector slug. One Google OAuth app
        means one registered redirect URI; the actual connector being
        connected (gmail / drive / calendar) lives inside the signed state.
        """
        from donna.core.integrations import OAuthStateInvalid
        from donna.core.integrations.oauth import BaseOAuthHandler

        from .models import ClientCredentials, OAuthToken
        from donna.users.models import User
        from donna.workspaces.models import Workspace

        # Decode state up front — signing salt is framework-level, no handler
        # or credentials row needed.
        state_payload = BaseOAuthHandler.verify_state(state)

        # The connector slug (gmail / drive / fathom) lives in the state.
        connector_slug = state_payload["slug"]
        cls = get_provider(connector_slug)
        if cls.oauth_provider_slug != slug:
            raise OAuthStateInvalid(
                f"state connector {connector_slug!r} "
                f"(vendor={cls.oauth_provider_slug!r}) does not match "
                f"callback vendor {slug!r}"
            )
        provider = cls()

        user = User.objects.get(id=state_payload["user_id"])
        workspace = Workspace.objects.get(id=state_payload["workspace_id"])

        # Pinned row — exchange the code with the exact client_id/secret
        # that signed the authorize URL.
        pinned_id = state_payload.get("client_credentials_id")
        if pinned_id:
            oauth_config = ClientCredentials.objects.get(id=pinned_id)
        else:
            # Legacy state payload without pinning — fall back to resolver.
            oauth_config = ClientCredentials.objects.resolve(
                cls.oauth_provider_slug, workspace=workspace
            )
            if oauth_config is None:
                raise NotConfigured(
                    f"No enabled ClientCredentials({cls.oauth_provider_slug!r}) "
                    f"row resolves for workspace={workspace.id}."
                )
        handler = provider.oauth_handler(oauth_config)

        response = handler.exchange_code(code)
        parsed = handler.parse_token_response(response)

        # Choose token scope based on connector configuration.
        token_owner_kwargs: dict
        if cls.token_scope == "workspace":
            token_owner_kwargs = {
                "workspace": workspace,
                "user":      None,
                "granter":   user,
            }
        else:  # "user"
            token_owner_kwargs = {
                "user":      user,
                "workspace": None,
                "granter":   None,
            }

        # Match the existing token by (provider, owner) so re-auth upserts.
        lookup = {"provider": oauth_config, **{
            k: v for k, v in token_owner_kwargs.items() if k != "granter"
        }}
        token, _ = OAuthToken.objects.update_or_create(
            **lookup,
            defaults={
                **token_owner_kwargs,
                "access_token":  parsed["access_token"],
                "refresh_token": parsed.get("refresh_token", ""),
                "expires_at":    parsed.get("expires_at"),
                "scope":         parsed.get("scope", ""),
            },
        )

        # Auto-create / refresh the Connection row for this connector.
        # See plans/08-connection-pattern.md "Pair flow → Connection
        # auto-creation". Sibling connectors that share the same OAuth
        # vendor (e.g. Drive after Gmail) lazy-create on first read of
        # their /subscription/ endpoint — not here.
        from .models import Connection

        conn_user = user if cls.token_scope == "user" else None
        connection, conn_created = Connection.objects.get_or_create(
            workspace=workspace,
            user=conn_user,
            # URL slug is the vendor; the connector identity (gmail / drive)
            # is what `Connection.provider_slug` should track.
            provider_slug=connector_slug,
            defaults={
                "token":  token,
                "config": dict(getattr(cls, "default_config", {}) or {}),
            },
        )
        if not conn_created and connection.token_id != token.id:
            connection.token = token
            connection.save(update_fields=["token", "updated_at"])

        # Per-connector post-connect hook (e.g. register a remote webhook).
        # Runs inside this @transaction.atomic block — any raise rolls back
        # the OAuthToken + Connection rows so we never leave a half-configured
        # binding behind. Hook implementations should be idempotent so a retry
        # after a transient vendor error works.
        try:
            # `on_connect` is optional per the IntegrationProvider contract
            # ("default implementations are no-ops"). Plain connector classes
            # with no vendor-side setup (poll-based Gmail/Drive) simply don't
            # define it — treat absence as a no-op instead of crashing the
            # whole callback (which rolls back the token + connection).
            on_connect = getattr(provider, "on_connect", None)
            if on_connect is not None:
                on_connect(token=token, connection=connection)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "on_connect_failed",
                extra={"slug": connector_slug, "error": str(exc)},
            )
            raise

        return token
