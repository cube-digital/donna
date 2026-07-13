"""Bundled hooks ship in this directory; ``chat.apps.ready()`` imports
this module so registration side-effects fire at startup."""
from . import audit  # noqa: F401 — register on import
