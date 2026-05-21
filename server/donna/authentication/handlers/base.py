"""Base class for OAuth login callback handlers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from donna.authentication.services import AuthService


class BaseOAuthHandler(ABC):
    """
    Abstract OAuth handler used internally by ``AuthService``.

    Implementations encapsulate the provider-specific logic for:
      - Building the authorize URL (with signed state).
      - Exchanging the callback code for tokens + user info.
      - Creating / matching the local ``User``.
      - Issuing the JWT redirect back to the frontend.
    """

    @abstractmethod
    def get_authorization_url(self, state: dict[str, Any]) -> str:
        """Return the URL to which the user should be sent for consent."""

    @abstractmethod
    def handle_callback(self, request, auth_service: "AuthService") -> dict[str, Any]:
        """
        Handle the provider's callback. Returns:

            {"redirect_url": str}                  — success (used by view to 302)
            {"redirect_url": str, "error": str}    — failure (error appended to URL)
        """
