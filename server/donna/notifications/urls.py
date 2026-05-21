"""
Notifications URL routes — mounted under ``/api/v1/notifications/`` by
``donna/urls.py``.

The SSE endpoint is a plain Django async view (``notifications_sse_view``)
rather than a DRF view because DRF's request lifecycle doesn't play well
with long-lived ``StreamingHttpResponse`` generators.
"""
from __future__ import annotations

from django.urls import path

from .api.v1.views import (
    MarkAllReadView,
    MarkReadView,
    NotificationListView,
    notifications_sse_view,
)


urlpatterns = [
    path("",               NotificationListView.as_view(), name="notification-list"),
    path("mark-read",      MarkReadView.as_view(),         name="notification-mark-read"),
    path("mark-all-read",  MarkAllReadView.as_view(),      name="notification-mark-all-read"),
    path("stream",         notifications_sse_view,         name="notification-stream"),
]
