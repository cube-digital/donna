"""
Integrations app config.

At startup we walk ``donna/integrations/connectors/`` for ``provider.py``
files and import each (so the ``@register`` decorator populates the runtime
registry). When a sibling ``tasks.py`` exists we import that too so each
connector's Celery ``@shared_task`` decorators run at boot.

Underscore-prefixed paths (``_shared/``, ``_draft/``, ``__pycache__``) are
skipped so they can carry vendor-level shared code without being mistaken for
connectors.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class IntegrationsConfig(AppConfig):
    name = "donna.integrations"
    label = "integrations"

    def ready(self):
        from . import connectors

        root = Path(connectors.__file__).parent
        package_prefix = "donna.integrations.connectors"

        for provider_py in sorted(root.rglob("provider.py")):
            rel = provider_py.relative_to(root)
            # Skip underscore-prefixed paths (vendor-level shared utilities)
            if any(part.startswith("_") for part in rel.parts):
                continue

            # Build dotted module path: providers/google/mail/provider.py →
            # donna.integrations.connectors.google.mail.provider
            module_path = (
                f"{package_prefix}." + str(rel.with_suffix("")).replace("/", ".")
            )

            try:
                importlib.import_module(module_path)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "connector_provider_import_failed",
                    extra={"module": module_path},
                )
                continue

            # Optional tasks.py sibling — connectors without async work skip this.
            tasks_module = module_path.rsplit(".", 1)[0] + ".tasks"
            try:
                importlib.import_module(tasks_module)
            except ModuleNotFoundError:
                continue
            except Exception:  # noqa: BLE001
                logger.exception(
                    "connector_tasks_import_failed",
                    extra={"module": tasks_module},
                )

        # Connect-time ingest notifications — importing the module registers the
        # debounce task; connect the post_save signal that drives it. One
        # receiver covers every connector (and webhook CDC) — see notifications.py.
        from django.db.models.signals import post_save

        from . import notifications
        from .models import DeliveryPackage

        post_save.connect(
            notifications.on_delivery_package_ingested,
            sender=DeliveryPackage,
            dispatch_uid="integrations.ingest_notify",
        )
