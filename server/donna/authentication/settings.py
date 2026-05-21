"""
Reloadable settings for the authentication module.

Defaults govern reset-password-token + email-verification-token TTLs,
per-user limits, and token length. Override by setting
``AUTHENTICATION = {...}`` in Django settings.

Pattern copied from narrio so the same admin/operational knobs work here.
"""
from datetime import timedelta

from django.conf import settings
from django.core.signals import setting_changed
from rest_framework.settings import APISettings


USER_SETTINGS = getattr(settings, "AUTHENTICATION", None)

DEFAULTS = {
    # Reset password
    "RESET_PASSWORD_TOKEN_CHARACTER_LENGTH": 64,
    "RESET_PASSWORD_TOKEN_TTL":               timedelta(hours=24),
    "RESET_PASSWORD_TOKEN_LIMIT_PER_USER":    3,

    # Email verification
    "EMAIL_VERIFY_TOKEN_CHARACTER_LENGTH":    64,
    "EMAIL_VERIFY_TOKEN_TTL":                 timedelta(days=7),
    "EMAIL_VERIFY_TOKEN_LIMIT_PER_USER":      5,
}

api_settings = APISettings(USER_SETTINGS, DEFAULTS)


def reload_api_settings(*args, **kwargs) -> None:  # pragma: no cover
    global api_settings

    setting, value = kwargs["setting"], kwargs["value"]
    if setting == "AUTHENTICATION":
        api_settings = APISettings(value, DEFAULTS)


setting_changed.connect(reload_api_settings)
