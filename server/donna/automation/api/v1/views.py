"""Plan 13 §7.1 — Schedule CRUD.

Workspace-scoped (header). Owner-of-AgentSession not enforced at v1 — any
authenticated workspace member can manage schedules on agents in the
same workspace. Tighten in v2 if/when a role model lands.
"""
from __future__ import annotations

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from donna.automation.models import Schedule

from .serializers import ScheduleSerializer


class ScheduleListCreateView(generics.ListCreateAPIView):
    """``GET/POST /api/v1/automation/schedules/``."""

    permission_classes = [IsAuthenticated]
    serializer_class = ScheduleSerializer

    def get_queryset(self):
        return Schedule.objects.filter(
            workspace=self.request.workspace,
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(
            workspace=self.request.workspace,
            created_by=self.request.user,
            updated_by=self.request.user,
        )


class ScheduleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """``GET/PATCH/DELETE /api/v1/automation/schedules/<id>/``."""

    permission_classes = [IsAuthenticated]
    serializer_class = ScheduleSerializer
    lookup_field = "id"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Schedule.objects.filter(workspace=self.request.workspace)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
