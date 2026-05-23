"""
Registry — slug → IntegrationProvider class lookup, populated by `@register`.

The registry is populated at app startup when each connector's `provider.py`
module is imported by `donna.integrations.apps.IntegrationsConfig.ready()`.

Connectors register themselves with the `@register` decorator on the provider
class. The decorator honours `settings.DISABLED_INTEGRATIONS` so a sysadmin can
opt-out individual connectors without code changes.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from donna.workspaces.models import Workspace

    from .provider import IntegrationProvider


from .exceptions import ProviderNotRegistered, SlugCollision


logger = logging.getLogger(__name__)


_REGISTRY: dict[str, type["IntegrationProvider"]] = {}


def register(cls: type["IntegrationProvider"]) -> type["IntegrationProvider"]:
    """
    Decorator that registers a connector class under its ``slug``.

    Honours ``settings.DISABLED_INTEGRATIONS`` — disabled slugs are imported
    but not added to the runtime registry (so tests can still reference the
    class while production never serves them).

    Usage:
        @register
        class FathomProvider:
            slug = "fathom"
            ...
    """
    from django.conf import settings

    slug = getattr(cls, "slug", None)
    if not slug or not isinstance(slug, str):
        raise SlugCollision(
            f"{cls!r} must declare a non-empty string class attribute `slug`"
        )

    disabled = getattr(settings, "DISABLED_INTEGRATIONS", ()) or ()
    if slug in disabled:
        logger.info("integration_registration_skipped", extra={"slug": slug, "reason": "disabled"})
        return cls

    existing = _REGISTRY.get(slug)
    if existing is not None and existing is not cls:
        raise SlugCollision(
            f"IntegrationProvider slug collision: {slug!r} is already registered "
            f"to {existing!r}; refusing to overwrite with {cls!r}"
        )

    _REGISTRY[slug] = cls
    logger.info("integration_registered", extra={"slug": slug, "cls": cls.__qualname__})
    return cls


def get(slug: str) -> type["IntegrationProvider"]:
    """
    Look up a registered provider class by slug.

    Raises ``ProviderNotRegistered`` when the slug isn't known (either the
    connector doesn't exist or it's disabled via DISABLED_INTEGRATIONS).
    """
    try:
        return _REGISTRY[slug]
    except KeyError as exc:
        raise ProviderNotRegistered(
            f"no integration registered under slug {slug!r}"
        ) from exc


def all_loaded() -> list[type["IntegrationProvider"]]:
    """All provider classes registered (modulo DISABLED_INTEGRATIONS)."""
    return list(_REGISTRY.values())


def configured_for_workspace(workspace: "Workspace") -> list[type["IntegrationProvider"]]:
    """
    All registered providers whose backing OAuthProvider row exists with
    ``is_enabled=True``. Filters by DB state at call time.

    The workspace argument is currently unused — every configured provider is
    available to every workspace. Kept on the signature so future per-workspace
    enablement (feature flags, plan tiers) is a one-line change.
    """
    # Imported lazily — registry is core/framework, OAuthProvider is app-model.
    from donna.integrations.models import ClientCredentials

    enabled_slugs = set(
        ClientCredentials.objects
        .filter(is_enabled=True)
        .values_list("slug", flat=True)
    )
    return [
        cls for cls in _REGISTRY.values()
        if cls.oauth_provider_slug in enabled_slugs
    ]


def _clear() -> None:
    """Test-only helper. Do not use in production code."""
    _REGISTRY.clear()
