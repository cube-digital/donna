"""
Status app URL routes — health check.

Tiny stub to unblock URL loading; expand with real status endpoints
when needed.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.urls import path


def healthcheck(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", healthcheck, name="status-health"),
]
