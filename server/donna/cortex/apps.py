"""
Cortex app config.

At startup we walk ``donna/cortex/templates/`` for ``*.py`` files
(excluding underscore-prefixed and ``__init__.py``) and import each so
the ``@register_type`` decorator populates the TypeSpec registry.
Mirrors the connector discovery pattern in
``donna/integrations/apps.py``.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class CortexConfig(AppConfig):
    name = "donna.cortex"
    label = "cortex"

    def ready(self):
        templates_root = Path(__file__).parent / "templates"
        if not templates_root.exists():
            return

        package_prefix = "donna.cortex.templates"

        for py_file in sorted(templates_root.rglob("*.py")):
            rel = py_file.relative_to(templates_root)
            if any(part.startswith("_") for part in rel.parts):
                continue
            if rel.name == "__init__.py":
                continue

            module_path = (
                f"{package_prefix}."
                + str(rel.with_suffix("")).replace("/", ".")
            )

            try:
                importlib.import_module(module_path)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "cortex_typespec_import_failed",
                    extra={"module": module_path},
                )
                continue
