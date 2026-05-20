"""
Authentication app models — OAuthProvider + OAuthToken.

`OAuthProvider` carries per-deployment OAuth-app configuration. The Donna team
populates it for Cloud (via env-var bootstrap); on-prem sysadmins populate it
via Django admin. One row per upstream vendor (Google's row backs Gmail + Drive
+ Calendar — see plans/05-integration-architecture.md#deployment-model).

`OAuthToken` is the per-user (or per-workspace) credential issued by the upstream
provider after the OAuth dance.
"""
import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from donna.core.db.fields import EncryptedTextField
from donna.core.db.models import TimestampsMixin, UserAuditMixin


class OAuthProvider(TimestampsMixin, UserAuditMixin):
    """
    Per-deployment OAuth-app configuration. One row per upstream vendor.

    Connector classes reference rows here via ``oauth_provider_slug``.
    Bootstrap (donna/integrations/management/commands/integrations_bootstrap.py)
    seeds default values from each connector's static attributes; Cloud
    additionally fills credentials from env vars at startup.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    # Identity
    slug = models.CharField(
        _("slug"),
        max_length=64,
        unique=True,
        help_text=_("Stable identifier; matches connector class `oauth_provider_slug`."),
    )
    display_name = models.CharField(_("display name"), max_length=120)

    # Master switch — until True, the provider doesn't appear to users.
    is_enabled = models.BooleanField(_("is enabled"), default=False)

    # OAuth-app credentials (set by the deployer)
    client_id = models.CharField(_("client id"), max_length=255, blank=True, default="")
    client_secret = EncryptedTextField(_("client secret"), null=True, blank=True)
    redirect_uri = models.URLField(_("redirect uri"), blank=True, default="")

    # Endpoints + scopes (seeded by bootstrap from connector defaults)
    authorize_url = models.URLField(_("authorize url"), blank=True, default="")
    token_url = models.URLField(_("token url"), blank=True, default="")
    default_scopes = models.JSONField(_("default scopes"), default=list, blank=True)

    # Webhook signing secret (when the provider sends webhooks)
    webhook_secret = EncryptedTextField(_("webhook secret"), null=True, blank=True)

    # Free-form provider-specific extras (e.g., Slack signing secret, region overrides)
    metadata = models.JSONField(_("metadata"), default=dict, blank=True)

    class Meta:
        db_table = "oauth_providers"
        verbose_name = _("OAuth Provider")
        verbose_name_plural = _("OAuth Providers")
        indexes = [
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.display_name or self.slug

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.slug!r} (id={self.id})>"


class OAuthToken(TimestampsMixin):
    """
    OAuth tokens for external service integrations.

    Per ``OAuthProvider`` × (User XOR Workspace):
    - User-scoped (Gmail per-user): ``user`` set, ``workspace`` null.
    - Workspace-scoped (Slack per-workspace): ``workspace`` set, ``user`` null,
      ``granter`` records the authorizing user for audit.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )

    provider = models.ForeignKey(
        OAuthProvider,
        on_delete=models.CASCADE,
        related_name="tokens",
        related_query_name="token",
    )

    # Exactly one of user/workspace is set (enforced via CheckConstraint).
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
        null=True,
        blank=True,
    )
    granter = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        related_name="granted_oauth_tokens",
        related_query_name="granted_oauth_token",
        null=True,
        blank=True,
        help_text=_("User who authorized a workspace-scoped token."),
    )

    # Token material
    access_token = EncryptedTextField(_("access token"), null=True, blank=True)
    refresh_token = EncryptedTextField(_("refresh token"), null=True, blank=True)
    expires_at = models.DateTimeField(
        _("access token expiry"),
        null=True,
        blank=True,
        help_text=_("When the current access_token expires (UTC)."),
    )
    scope = models.TextField(_("scope"), null=True, blank=True)

    class Meta:
        db_table = "oauth_tokens"
        verbose_name = _("OAuth token")
        verbose_name_plural = _("OAuth tokens")
        constraints = [
            # Exactly one of user / workspace is set.
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, workspace__isnull=True)
                    | models.Q(user__isnull=True, workspace__isnull=False)
                ),
                name="oauth_token_has_exactly_one_owner",
            ),
            # One user-scoped token per provider per user.
            models.UniqueConstraint(
                fields=["provider", "user"],
                condition=models.Q(user__isnull=False),
                name="uq_oauth_token_per_user_provider",
            ),
            # One workspace-scoped token per provider per workspace.
            models.UniqueConstraint(
                fields=["provider", "workspace"],
                condition=models.Q(workspace__isnull=False),
                name="uq_oauth_token_per_workspace_provider",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "user"]),
            models.Index(fields=["provider", "workspace"]),
        ]

    def __str__(self):
        owner = self.user or self.workspace
        return f"{self.provider} - {owner}"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"provider={self.provider_id} user={self.user_id} workspace={self.workspace_id}>"
        )
