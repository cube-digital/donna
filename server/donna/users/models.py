from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.files.storage import default_storage
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Global identity, keyed by email. A user can belong to many workspaces."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)

    # Mention handle (resolves @<handle>). Backfilled from email-prefix at
    # signup; collisions disambiguate with numeric suffix. Editable later
    # via profile settings; stays unique workspace-wide-globally to keep
    # mention parsing trivial across workspaces.
    handle = models.CharField(
        max_length=40,
        unique=True,
        null=True,
        blank=True,
        help_text="Lowercase mention handle, e.g. 'alice' resolves @alice.",
    )

    # Profile picture — stored in STORAGES["default"] (S3 in cloud). Plain
    # FileField (no Pillow dep); content-type is validated at the upload view.
    # Empty → the UI renders coloured initials.
    picture = models.FileField(
        _("profile picture"),
        upload_to="users/pictures/",
        storage=default_storage,
        max_length=500,
        blank=True,
        null=True,
    )
    # Free-text status message (Slack-style), e.g. "On a call".
    status = models.CharField(_("status"), max_length=140, blank=True, default="")

    # Email verification — soft gate. v1: signup allowed without verifying,
    # frontend nags the user. Google login flips this to True (Google has
    # already attested the email).
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        db_table = "users"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email
