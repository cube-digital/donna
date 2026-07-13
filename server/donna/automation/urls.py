"""Automation HTTP routes — mounted under ``/api/v1/automation/`` by
``donna/urls.py``."""
from __future__ import annotations

from django.urls import path

from .api.v1.views import ScheduleDetailView, ScheduleListCreateView


urlpatterns = [
    path("schedules/", ScheduleListCreateView.as_view(), name="automation-schedule-list"),
    path("schedules/<uuid:id>/", ScheduleDetailView.as_view(), name="automation-schedule-detail"),
]
