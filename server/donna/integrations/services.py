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
    from donna.authentication.models import OAuthProvider, OAuthToken
    from donna.users.models import User
    from donna.workspaces.models import Workspace


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
        from donna.authentication.models import OAuthProvider, OAuthToken

        enabled_slugs = set(
            OAuthProvider.objects
            .filter(is_enabled=True)
            .values_list("slug", flat=True)
        )
        connected_oauth_slugs = set(
            OAuthToken.objects
            .filter(workspace=workspace)
            .values_list("provider__slug", flat=True)
        )
        # Also include user-scoped tokens for the current user.
        if self.current_user is not None:
            connected_oauth_slugs |= set(
                OAuthToken.objects
                .filter(user=self.current_user)
                .values_list("provider__slug", flat=True)
            )

        statuses: list[IntegrationStatus] = []
        for cls in all_loaded():
            statuses.append(
                IntegrationStatus(
                    slug=cls.slug,
                    display_name=cls.display_name,
                    category=cls.category,
                    is_configured=cls.oauth_provider_slug in enabled_slugs,
                    is_connected=cls.oauth_provider_slug in connected_oauth_slugs,
                )
            )
        return statuses

    def get_status(self, workspace: "Workspace", slug: str) -> IntegrationStatus:
        """Status for one connector. Raises ProviderNotRegistered if unknown."""
        from django.db.models import Q

        from donna.authentication.models import OAuthProvider, OAuthToken

        cls = get_provider(slug)  # raises ProviderNotRegistered

        is_configured = OAuthProvider.objects.filter(
            slug=cls.oauth_provider_slug, is_enabled=True
        ).exists()

        # Caller sees a connection if either the workspace has one, or the
        # current user has a personal one.
        owner_clause = Q(workspace=workspace)
        if self.current_user is not None:
            owner_clause |= Q(user=self.current_user)

        is_connected = OAuthToken.objects.filter(
            provider__slug=cls.oauth_provider_slug,
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
        from donna.authentication.models import OAuthProvider

        cls = get_provider(slug)
        provider = cls()

        try:
            oauth_config = OAuthProvider.objects.get(slug=cls.oauth_provider_slug)
        except OAuthProvider.DoesNotExist as exc:
            raise NotConfigured(
                f"OAuthProvider({cls.oauth_provider_slug!r}) row is missing"
            ) from exc
        if not oauth_config.is_enabled:
            raise NotConfigured(
                f"OAuthProvider({cls.oauth_provider_slug!r}) is disabled"
            )

        handler = provider.oauth_handler(oauth_config)
        state_payload = {
            "user_id":      str(user.id),
            "workspace_id": str(workspace.id),
            "slug":         slug,
            "redirect_to":  redirect_to or "",
        }
        return handler.build_authorize_url(state_payload=state_payload)

    # ── Disconnect ──────────────────────────────────────────────────────────
    @transaction.atomic
    def disconnect(self, workspace: "Workspace", user: "User", slug: str) -> bool:
        """
        Revoke + delete the OAuthToken for this caller. Returns True when a
        token was removed, False when nothing was connected.
        """
        from donna.authentication.models import OAuthProvider, OAuthToken

        cls = get_provider(slug)
        provider = cls()

        try:
            oauth_config = OAuthProvider.objects.get(slug=cls.oauth_provider_slug)
        except OAuthProvider.DoesNotExist:
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
        """
        from donna.authentication.models import OAuthProvider, OAuthToken
        from donna.users.models import User
        from donna.workspaces.models import Workspace

        cls = get_provider(slug)
        provider = cls()
        oauth_config = OAuthProvider.objects.get(slug=cls.oauth_provider_slug)
        handler = provider.oauth_handler(oauth_config)

        state_payload = handler.verify_state(state)
        user = User.objects.get(id=state_payload["user_id"])
        workspace = Workspace.objects.get(id=state_payload["workspace_id"])

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
        return token
