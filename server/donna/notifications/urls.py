"""
Notifications URL routes — mounted under ``/api/v1/notifications/`` by
``donna/urls.py``.

Generated routes:

  GET   /api/v1/notifications/                 NotificationViewSet.list
  GET   /api/v1/notifications/{id}/            NotificationViewSet.retrieve
  PATCH /api/v1/notifications/seen/            NotificationViewSet.seen
  GET   /api/v1/notifications/stream           notifications_sse_view (async)

The SSE endpoint is a plain Django async view (not DRF) because DRF's
request lifecycle doesn't play well with long-lived
``StreamingHttpResponse`` generators.
"""
from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .api.v1.views import NotificationViewSet, notifications_sse_view


router = DefaultRouter()
router.register(r"", NotificationViewSet, basename="notification")


urlpatterns = [
    # Async SSE — registered before router so it wins over router 404 fallthrough.
    path("stream", notifications_sse_view, name="notification-stream"),
    *router.urls,
]
