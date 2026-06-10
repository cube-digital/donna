from __future__ import annotations

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """
    Append-only audit trail for workspace, channel, and membership events.

    Records are written via :func:`donna.audit.services.AuditService.record`
    from inside service-layer mutations. There is no HTTP write path —
    the log is internal, immutable, and queried (when needed) directly
    via the ORM or admin. A read endpoint can be added later when the
    UI surfaces it.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "donna.audit"
    label = "audit"
