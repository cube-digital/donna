"""Donna automation app config — Plan 13 §7."""
from __future__ import annotations

from django.apps import AppConfig


class AutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "donna.automation"
    label = "automation"
