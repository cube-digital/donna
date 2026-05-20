"""
URL routing for the integrations app.

Mounted under ``/api/v1/`` by the project urls.py. Generates:

  GET    /api/v1/integrations/                                  list
  GET    /api/v1/integrations/{slug}/                           retrieve
  POST   /api/v1/integrations/{slug}/connect/                   connect action
  POST   /api/v1/integrations/{slug}/disconnect/                disconnect action
  POST   /api/v1/integrations/{slug}/webhook/callback           public webhook
  GET    /api/v1/integrations/{slug}/oauth/callback             public OAuth callback
"""
from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api.v1.oauth import ProviderOAuthCallbackView
from .api.v1.views import IntegrationViewSet
from .api.v1.webhooks import ProviderWebhookView


router = DefaultRouter()
router.register(r"integrations", IntegrationViewSet, basename="integration")


urlpatterns = [
    *router.urls,

    # Public, non-tenanted endpoints — listed in WorkspaceMiddleware.IGNORED_SUFFIXES.
    path(
        "integrations/<slug:slug>/webhook/callback",
        ProviderWebhookView.as_view(),
        name="integration-webhook-callback",
    ),
    path(
        "integrations/<slug:slug>/oauth/callback",
        ProviderOAuthCallbackView.as_view(),
        name="integration-oauth-callback",
    ),
]
