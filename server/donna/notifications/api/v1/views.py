"""
Notifications API views.

  GET  /api/v1/notifications/                 list current user's alerts
  POST /api/v1/notifications/mark-read        body: {ids: [...]}
  POST /api/v1/notifications/mark-all-read
  GET  /api/v1/notifications/stream           SSE (async)

``stream`` is an async view that streams Redis pubsub messages over
SSE. Requires an ASGI server (uvicorn — already in deps). The other
endpoints are plain sync DRF views.
"""
from __future__ import annotations

import logging
from http import HTTPStatus

from channels.db import database_sync_to_async
from django.http import StreamingHttpResponse
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import Notification
from ...services import NotificationService
from .serializers import MarkReadSerializer, NotificationSerializer


@database_sync_to_async
def _get_user_workspace_ids(user_id) -> list[str]:
    """Read all workspace IDs the user belongs to. Sync ORM in async context."""
    from donna.workspaces.models import WorkspaceMembership

    return [
        str(wid)
        for wid in WorkspaceMembership.objects.filter(user_id=user_id)
        .values_list("workspace_id", flat=True)
    ]


logger = logging.getLogger(__name__)


class NotificationListView(generics.ListAPIView):
    """Paginated list of the current user's notifications."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")


class MarkReadView(APIView):
    """Bulk-mark notifications as read."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = NotificationService.mark_as_read(
            request.user, [str(i) for i in serializer.validated_data["ids"]]
        )
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = NotificationService.mark_all_read(request.user)
        return Response({"updated": updated}, status=status.HTTP_200_OK)


# ── SSE stream (async) ──────────────────────────────────────────────────────
async def notifications_sse_view(request):
    """
    Server-Sent Events stream for the current user.

    Subscribes to three flavours of channels per user (see
    plans/10-realtime-layer.md):

    - ``user-{uid}-notifications``         — personal
    - ``workspace-{wid}-notifications``    — for every wid the user belongs to
    - ``user-{uid}-workspace-{wid}-feed``  — for every wid the user belongs to
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return StreamingHttpResponse(
            iter([
                f"event: error\ndata: {{\"error\": \"unauthenticated\"}}\n\n",
            ]),
            status=int(HTTPStatus.UNAUTHORIZED),
            content_type="text/event-stream",
        )

    workspace_ids = await _get_user_workspace_ids(user.id)

    channels = [NotificationService.get_channel_name(str(user.id))]
    for wid in workspace_ids:
        channels.append(NotificationService.get_workspace_channel_name(wid))
        channels.append(
            NotificationService.get_user_workspace_feed_channel(str(user.id), wid)
        )

    async def stream():
        async for chunk in NotificationService.create_sse_stream_multi(channels):
            yield chunk

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"        # nginx: disable proxy buffering
    return response
