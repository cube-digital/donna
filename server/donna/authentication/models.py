"""
Authentication app models — password reset + email verification tokens.

OAuth-related models (``ClientCredentials`` — was ``OAuthProvider`` —
and ``OAuthToken``) moved to ``donna.integrations.models``. They belong
to the integration framework, not to user authentication.
"""
import secrets
import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .settings import api_settings


def _generate_token(length: int) -> str:
    """URL-safe random token. Trims to ``length`` chars."""
    return secrets.token_urlsafe(length)[:length]


class ResetPasswordManager(models.Manager):
    """Convenience methods for the reset-password token lifecycle."""

    def clean_expired_tokens(self) -> int:
        """Hard-delete tokens older than the TTL."""
        threshold = timezone.now() - api_settings.RESET_PASSWORD_TOKEN_TTL
        deleted, _ = self.filter(expiry_at__lte=threshold).delete()
        return deleted


class ResetPasswordToken(models.Model):
    """
    One-time secret for the password-recovery flow.

    A user may have multiple active tokens up to
    ``api_settings.RESET_PASSWORD_TOKEN_LIMIT_PER_USER``. Each token
    expires after ``api_settings.RESET_PASSWORD_TOKEN_TTL`` (default 24h).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    key = models.CharField(max_length=64, db_index=True, unique=True)
    created_at = models.DateTimeField(_("token generation time"), auto_now_add=True)
    expiry_at = models.DateTimeField(_("token expiration time"), null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="reset_password_tokens",
        related_query_name="reset_password_token",
    )

    objects = ResetPasswordManager()

    class Meta:
        db_table = "reset_password_tokens"
        verbose_name = _("Reset password token")
        verbose_name_plural = _("Reset password tokens")

    def save(self, *args, **kwargs):
        length = api_settings.RESET_PASSWORD_TOKEN_CHARACTER_LENGTH
        if not self.key:
            self.key = _generate_token(length)
        if not self.expiry_at:
            self.expiry_at = timezone.now() + api_settings.RESET_PASSWORD_TOKEN_TTL
        return super().save(*args, **kwargs)

    def has_expired(self) -> bool:
        return timezone.now() > self.expiry_at

    def __str__(self):
        return f"({self.created_at} | {self.expiry_at})"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"created_at={self.created_at}, expiry_at={self.expiry_at}>"
        )


class EmailVerificationManager(models.Manager):
    """Lifecycle helpers for email-verification tokens."""

    def clean_expired_tokens(self) -> int:
        threshold = timezone.now() - api_settings.EMAIL_VERIFY_TOKEN_TTL
        deleted, _ = self.filter(expiry_at__lte=threshold).delete()
        return deleted


class EmailVerificationToken(models.Model):
    """
    One-time secret used to confirm a user's email address.

    Issued by ``POST /api/auth/email/verify/request`` (authed) and
    consumed by ``GET /api/auth/email/verify/confirm/<key>``. On success
    flips ``User.email_verified=True`` and stamps ``email_verified_at``.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        db_index=True,
    )
    key = models.CharField(max_length=64, db_index=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expiry_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="email_verification_tokens",
        related_query_name="email_verification_token",
    )

    objects = EmailVerificationManager()

    class Meta:
        db_table = "email_verification_tokens"
        verbose_name = _("Email verification token")
        verbose_name_plural = _("Email verification tokens")

    def save(self, *args, **kwargs):
        length = api_settings.EMAIL_VERIFY_TOKEN_CHARACTER_LENGTH
        if not self.key:
            self.key = _generate_token(length)
        if not self.expiry_at:
            self.expiry_at = timezone.now() + api_settings.EMAIL_VERIFY_TOKEN_TTL
        return super().save(*args, **kwargs)

    def has_expired(self) -> bool:
        return timezone.now() > self.expiry_at

    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def __str__(self):
        return f"({self.user_id} | {self.created_at})"

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: "
            f"user={self.user_id} created_at={self.created_at}>"
        )
