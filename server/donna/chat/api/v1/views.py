"""
Chat HTTP REST API.

WS handles realtime push; HTTP handles persistence + history. Frontend
flow: REST loads channel list + history on open, then WS pushes new
events. ``POST /messages`` and WS ``send_message`` both call into the
same ``ChannelService`` so the broadcast path is identical.
"""
from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import Channel, ChannelMembership, ChannelReadState, Message
from ...services import ChannelService
from .serializers import (
    AdvanceReadSerializer,
    ChannelCreateSerializer,
    ChannelSerializer,
    DMOpenSerializer,
    MessageCreateSerializer,
    MessageEditSerializer,
    MessageSerializer,
    ReadStateSerializer,
)


logger = logging.getLogger(__name__)


def _require_channel_membership(user, channel: Channel) -> ChannelMembership:
    try:
        return ChannelMembership.objects.get(user=user, channel=channel)
    except ChannelMembership.DoesNotExist as exc:
        raise PermissionDenied("not a member of this channel") from exc


# ── Channels ────────────────────────────────────────────────────────────────
class ChannelListCreateView(generics.ListCreateAPIView):
    """List the caller's channels in the current workspace; create new channel."""

    serializer_class = ChannelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Channel.objects.filter(
                workspace=self.request.workspace,
                memberships__user=self.request.user,
            )
            .distinct()
            .order_by("name")
        )

    def create(self, request, *args, **kwargs):
        serializer = ChannelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        channel = Channel.objects.create(
            workspace=request.workspace,
            kind=Channel.Kind.CHANNEL,
            name=data["name"],
            slug=data.get("slug") or "",
            topic=data.get("topic") or "",
            visibility=data.get("visibility") or Channel.Visibility.PUBLIC,
            created_by=request.user,
            updated_by=request.user,
        )
        ChannelMembership.objects.create(
            channel=channel, user=request.user, role=ChannelMembership.Role.ADMIN
        )
        ChannelService.emit_channel_created(channel)
        return Response(
            ChannelSerializer(channel).data, status=status.HTTP_201_CREATED
        )


class ChannelDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = ChannelSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        return Channel.objects.filter(
            workspace=self.request.workspace,
            memberships__user=self.request.user,
        ).distinct()


# ── Messages ────────────────────────────────────────────────────────────────
class ChannelMessageListCreateView(APIView):
    """``/chat/channels/{id}/messages/`` — list (paginated) + create."""

    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace
        )
        _require_channel_membership(request.user, channel)

        limit = min(int(request.query_params.get("limit", 50)), 200)
        before = request.query_params.get("before")
        qs = Message.objects.filter(channel=channel).order_by("-created_at")
        if before:
            try:
                anchor = Message.objects.get(id=before)
                qs = qs.filter(created_at__lt=anchor.created_at)
            except Message.DoesNotExist:
                pass
        page = list(qs[:limit])
        # Return in chronological order (oldest first).
        page.reverse()
        return Response(MessageSerializer(page, many=True).data)

    def post(self, request, id):
        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace
        )
        _require_channel_membership(request.user, channel)

        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = ChannelService.send_message(
            channel=channel,
            sender_user=request.user,
            body=serializer.validated_data["body"],
            client_msg_id=serializer.validated_data.get("client_msg_id"),
        )
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageDetailView(APIView):
    """``/chat/messages/{id}/`` — edit / delete."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, id):
        message = get_object_or_404(
            Message, id=id, channel__workspace=request.workspace
        )
        if message.author_user_id != request.user.id:
            raise PermissionDenied("only the author can edit a message")

        serializer = MessageEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = ChannelService.edit_message(
            message=message, body=serializer.validated_data["body"]
        )
        return Response(MessageSerializer(updated).data)

    def delete(self, request, id):
        message = get_object_or_404(
            Message, id=id, channel__workspace=request.workspace
        )
        if message.author_user_id != request.user.id:
            raise PermissionDenied("only the author can delete a message")
        ChannelService.delete_message(message=message)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── DMs ─────────────────────────────────────────────────────────────────────
class DMOpenView(APIView):
    """POST /chat/dms/ → returns the DM Channel between caller + peer."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DMOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from donna.users.models import User
        try:
            peer = User.objects.get(id=serializer.validated_data["peer_user_id"])
        except User.DoesNotExist as exc:
            raise NotFound("peer not found") from exc

        try:
            channel = ChannelService.get_or_create_dm(request.user, peer)
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"peer_user_id": str(exc)}) from exc
        return Response(ChannelSerializer(channel).data)


# ── Read state ──────────────────────────────────────────────────────────────
class ChannelReadStateView(APIView):
    """``/chat/channels/{id}/read-state/`` — read + advance."""

    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace
        )
        _require_channel_membership(request.user, channel)

        state = ChannelReadState.objects.filter(
            user=request.user, channel=channel
        ).first()
        unread = ChannelService.unread_count(user=request.user, channel=channel)
        if state is None:
            return Response(
                {
                    "id":                 None,
                    "user":               str(request.user.id),
                    "channel":            str(channel.id),
                    "last_read_message":  None,
                    "last_read_at":       None,
                    "unread_count":       unread,
                }
            )
        data = ReadStateSerializer(state).data
        data["unread_count"] = unread
        return Response(data)

    def post(self, request, id):
        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace
        )
        _require_channel_membership(request.user, channel)

        serializer = AdvanceReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            message = Message.objects.get(
                id=serializer.validated_data["message_id"], channel=channel
            )
        except Message.DoesNotExist as exc:
            raise NotFound("message not found in channel") from exc

        state = ChannelService.advance_read_pointer(
            user=request.user, channel=channel, message=message
        )
        data = ReadStateSerializer(state).data
        data["unread_count"] = ChannelService.unread_count(
            user=request.user, channel=channel
        )
        return Response(data)
