"""
TypeSpec definitions per entity type.

Each ``<type>.py`` module here registers a ``TypeSpec`` via
``donna.cortex.registry.register_type`` at import time. Imports happen
during ``CortexConfig.ready()`` so the registry is populated before
any request hits the writer.

Companion Jinja templates live alongside as ``<type>.j2``. Underscore-
prefixed paths (``_partials/``) are reserved for Jinja includes and
skipped by the discovery walker.
"""
