"""
Integration framework exceptions.

These are pure framework errors; concrete provider modules can raise them
or subclass them. No app-model dependencies.
"""
from __future__ import annotations


class IntegrationError(Exception):
    """Base class for all integration framework errors."""


class NotConfigured(IntegrationError):
    """Raised when an OAuthProvider row is missing or is_enabled=False."""


class WebhookSignatureInvalid(IntegrationError):
    """Raised when an incoming webhook fails signature verification."""


class WebhookPayloadInvalid(IntegrationError):
    """Raised when an incoming webhook payload cannot be parsed or is malformed."""


class WorkspaceResolutionFailed(IntegrationError):
    """Raised when the provider cannot map an incoming event to a workspace."""


class OAuthError(IntegrationError):
    """Base class for OAuth lifecycle errors."""


class OAuthStateInvalid(OAuthError):
    """Raised when the OAuth callback state token is missing, expired, or tampered."""


class OAuthExchangeFailed(OAuthError):
    """Raised when exchanging an authorization code for tokens fails upstream."""


class TokenRefreshFailed(OAuthError):
    """Raised when refreshing an OAuth access token fails upstream."""


class ProviderNotRegistered(IntegrationError):
    """Raised when a slug doesn't resolve to a registered provider class."""


class SlugCollision(IntegrationError):
    """Raised when two provider classes try to register under the same slug."""
