"""Cortex app config.

Refactored 2026-06-14: replaced the templates/ walk + per-type Python
file discovery with a single declarative table in ``cortex/types.py``.
``ready()`` imports that module; the side-effect registers all 12
TypeSpecs in ``donna.cortex.registry``.
"""
from __future__ import annotations

import logging

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class CortexConfig(AppConfig):
    name = "donna.cortex"
    label = "cortex"

    def ready(self) -> None:
        try:
            import donna.cortex.types  # noqa: F401 — registers TypeSpecs as a side effect
        except Exception:  # noqa: BLE001
            logger.exception("cortex_types_import_failed")
