"""
Integration framework — cross-cutting primitives shared by every connector.

Contents are pure framework: Protocols, abstract base classes, and a registry.
No app-model dependencies at import time (`TYPE_CHECKING` for type hints only).

Concrete connectors live in `donna/integrations/connectors/<vendor>/<product>/`.
The integration app's `apps.py:ready()` auto-discovers them at startup.

Re-exports the public surface so consumers import from one place:

    from donna.core.integrations import (
        IntegrationProvider, BaseHTTPClient, BaseWebhookHandler,
        BaseOAuthHandler, BaseAdapter, register, get, all_loaded,
    )
"""
from __future__ import annotations

from .adapter import BaseAdapter, BaseEntityAdapter
from .canonical import CanonicalEntity
from .client import BaseHTTPClient
from .exceptions import (
    IntegrationError,
    NotConfigured,
    OAuthError,
    OAuthExchangeFailed,
    OAuthStateInvalid,
    ProviderNotRegistered,
    SlugCollision,
    TokenRefreshFailed,
    WebhookPayloadInvalid,
    WebhookSignatureInvalid,
    WorkspaceResolutionFailed,
)
from .oauth import BaseOAuthHandler
from .provider import IntegrationProvider, TokenScope, validate_against_schema
from .registry import (
    all_loaded,
    configured_for_workspace,
    get,
    register,
)
from .webhook import BaseWebhookHandler


__all__ = [
    # Protocol + base classes
    "IntegrationProvider",
    "TokenScope",
    "validate_against_schema",
    "BaseHTTPClient",
    "BaseWebhookHandler",
    "BaseOAuthHandler",
    "BaseAdapter",
    "BaseEntityAdapter",
    "CanonicalEntity",
    # Registry
    "register",
    "get",
    "all_loaded",
    "configured_for_workspace",
    # Exceptions
    "IntegrationError",
    "NotConfigured",
    "ProviderNotRegistered",
    "SlugCollision",
    "WebhookSignatureInvalid",
    "WebhookPayloadInvalid",
    "WorkspaceResolutionFailed",
    "OAuthError",
    "OAuthStateInvalid",
    "OAuthExchangeFailed",
    "TokenRefreshFailed",
]
