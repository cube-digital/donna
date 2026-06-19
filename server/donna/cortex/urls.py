"""Cortex URL routes (mounted under /api/v1/cortex/)."""
from __future__ import annotations

from rest_framework.routers import DefaultRouter

from donna.cortex.api.v1.views import CortexEntityViewSet


router = DefaultRouter()
router.register(r"entities", CortexEntityViewSet, basename="cortex-entity")

urlpatterns = router.urls
