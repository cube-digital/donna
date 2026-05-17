import uuid

from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from donna.core.db.models import TimestampsMixin, UserAuditMixin
from donna.core.db.fields import EncryptedTextField


class OAuthProvider(TimestampsMixin, UserAuditMixin):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    name = models.CharField(max_length=255)

    # OAuth credentials
    client_id = EncryptedTextField(_("client id"))
    client_secret = EncryptedTextField(_("client secret"))
    redirect_uri = models.URLField(_("redirect uri"))
    scopes = models.JSONField(_("scopes"), default=list)

    # OAuth configuration
    configuration = models.JSONField(_("configuration"), default=dict)

    class Meta:
        db_table = "oauth_providers"
        verbose_name = _("OAuth Provider")
        verbose_name_plural = _("OAuth Providers")
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<({self.__class__.__name__}:{self.id}): {self.name}>"


class OAuthToken(TimestampsMixin):
    """
    OAuth tokens for external service integrations.
    Stores refresh tokens for services like HubSpot and Google.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    provider = models.CharField(
        _("provider"),
        max_length=50,
        choices=OAuthProvider.choices,
    )
    access_token = EncryptedTextField(_("access token"), null=True, blank=True)
    refresh_token = EncryptedTextField(_("refresh token"))
    expires_at = models.DateTimeField(
        _("access token expiry"),
        null=True,
        blank=True,
        help_text="When the current access_token expires (UTC).",
    )
    scope = models.TextField(_("scope"), null=True, blank=True)

    # Foreign Keys
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
    )

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="oauth_tokens",
        related_query_name="oauth_token",
    )

    provider = models.ForeignKey(
        OAuthProvider,
        on_delete=models.CASCADE,
        related_name="tokens",
        related_query_name="token",
    )

    class Meta:
        db_table = "oauth_tokens"
        verbose_name = _("OAuth token")
        verbose_name_plural = _("OAuth tokens")
        unique_together = [["user", "provider"]]

    def __str__(self):
        return f"{self.user} - {self.provider}"

    def __repr__(self):
        return f"<{self.__class__.__name__}: (user={self.user_id}, provider={self.provider})>"

