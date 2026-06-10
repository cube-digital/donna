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
    AddMemberSerializer,
    AdvanceReadSerializer,
    ChannelCreateSerializer,
    ChannelMembershipSerializer,
    ChannelSerializer,
    ChannelUpdateSerializer,
    DMOpenSerializer,
    GroupDMOpenSerializer,
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
        """
        By default lists only channels the caller is a member of.

        Pass ``?include_public=true`` to also surface public named
        channels in the workspace the caller hasn't joined yet
        (Slack-style "browse"). Self-join is then a POST to
        ``/chat/channels/{id}/members/``.

        GUEST role: include_public is silently ignored — guests only
        see channels they were explicitly added to. The role-aware
        filter lives in :meth:`ChannelService.visible_channels`.
        """
        include_public = (
            self.request.query_params.get("include_public", "").lower()
            in ("1", "true", "yes")
        )
        return (
            ChannelService.visible_channels(
                user=self.request.user,
                workspace=self.request.workspace,
                include_public=include_public,
            )
            .order_by("name")
        )

    def create(self, request, *args, **kwargs):
        # Guests can be members of channels but cannot create them.
        try:
            ChannelService.refuse_if_guest(
                user=request.user,
                workspace=request.workspace,
                action="create channels",
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc

        # ``context={"request": request}`` so the slug validator can
        # check workspace-scoped uniqueness before the DB CHECK fires.
        serializer = ChannelCreateSerializer(
            data=request.data, context={"request": request},
        )
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
            modified_by=request.user,
        )
        ChannelMembership.objects.create(
            channel=channel, user=request.user, role=ChannelMembership.Role.ADMIN
        )
        ChannelService.emit_channel_created(channel)
        return Response(
            ChannelSerializer(channel).data, status=status.HTTP_201_CREATED
        )


class ChannelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """``/chat/channels/{id}/`` — retrieve / PATCH (name/topic/visibility) / DELETE.

    Membership gates retrieve + delete; only the admin role on the channel
    can update or delete. We don't expose PUT — patch is partial only.
    """

    serializer_class = ChannelSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "id"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        """
        Members see every channel they belong to. Non-members also see
        PUBLIC named channels in the workspace (so GET works for the
        browse-without-join flow). PATCH/DELETE are still gated by
        ``_require_admin`` below, so visibility is read-only for non
        members. Guest gating is centralized in
        :meth:`ChannelService.visible_channels`.
        """
        return ChannelService.visible_channels(
            user=self.request.user,
            workspace=self.request.workspace,
            include_public=True,
        )

    def _require_admin(self, channel):
        membership = _require_channel_membership(self.request.user, channel)
        if membership.role != ChannelMembership.Role.ADMIN:
            raise PermissionDenied("channel admin role required")

    def partial_update(self, request, *args, **kwargs):
        channel = self.get_object()
        self._require_admin(channel)

        serializer = ChannelUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        # Snapshot fields we audit before mutating.
        old_settings = dict(channel.settings or {})

        for field, value in validated.items():
            setattr(channel, field, value)
        channel.modified_by = request.user
        channel.save()
        ChannelService.emit_channel_updated(channel)

        if "settings" in validated:
            from donna.audit.services import AuditService
            AuditService.record(
                action="channel.settings.updated",
                actor=request.user,
                workspace=channel.workspace,
                target=channel,
                context={"before": old_settings, "after": dict(channel.settings)},
            )
        return Response(ChannelSerializer(channel).data)

    def destroy(self, request, *args, **kwargs):
        channel = self.get_object()
        self._require_admin(channel)
        channel_id = str(channel.id)
        workspace_id = str(channel.workspace_id)
        channel.delete()
        ChannelService.emit_channel_deleted(channel_id, workspace_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        try:
            ChannelService.authorize_delete_message(
                user=request.user, message=message
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        ChannelService.delete_message(message=message)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Channel membership ──────────────────────────────────────────────────────
def _get_workspace_channel(request, channel_id) -> Channel:
    """Resolve a channel scoped to the active workspace, 404 otherwise."""
    try:
        return Channel.objects.get(id=channel_id, workspace=request.workspace)
    except Channel.DoesNotExist as exc:
        raise NotFound("channel not found") from exc


class ChannelMembersView(APIView):
    """
    ``/chat/channels/{cid}/members/``

    - ``GET``  — list memberships (caller must be a channel member).
    - ``POST`` — admin-add (caller is channel admin, body ``{user_id, role?}``)
                  or self-join (body empty / ``{user_id: <caller-id>}``,
                  only on PUBLIC channels).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        channel = _get_workspace_channel(request, id)
        _require_channel_membership(request.user, channel)
        memberships = (
            ChannelMembership.objects
            .filter(channel=channel)
            .order_by("role", "user_id")
        )
        return Response(ChannelMembershipSerializer(memberships, many=True).data)

    def post(self, request, id):
        channel = _get_workspace_channel(request, id)

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user_id = serializer.validated_data.get("user_id")
        requested_role = serializer.validated_data.get(
            "role", ChannelMembership.Role.MEMBER
        )

        is_self_join = (
            target_user_id is None or str(target_user_id) == str(request.user.id)
        )

        if is_self_join:
            # Self-join only on public channels. Guests cannot self-join
            # (workspace-level role gate); they can only be added by a
            # channel admin (the admin-add branch below).
            try:
                ChannelService.refuse_if_guest(
                    user=request.user,
                    workspace=channel.workspace,
                    action="self-join channels",
                )
            except PermissionError as exc:
                raise PermissionDenied(str(exc)) from exc
            if channel.visibility != Channel.Visibility.PUBLIC:
                raise PermissionDenied(
                    "self-join is only allowed on public channels"
                )
            target_user = request.user
            role = ChannelMembership.Role.MEMBER
        else:
            # Admin-add — caller must be a channel ADMIN, OR a regular
            # member if the channel opts in via the documented
            # ``allow_member_invites`` setting (Phase 2c).
            caller_membership = _require_channel_membership(request.user, channel)
            caller_is_admin = (
                caller_membership.role == ChannelMembership.Role.ADMIN
            )
            members_can_invite = bool(channel.get_setting("allow_member_invites"))
            if not (caller_is_admin or members_can_invite):
                raise PermissionDenied(
                    "channel admin role required to add members"
                )
            from donna.users.models import User
            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist as exc:
                raise NotFound("target user not found") from exc
            # Non-admin inviters cannot grant ADMIN role.
            if (
                not caller_is_admin
                and requested_role == ChannelMembership.Role.ADMIN
            ):
                raise PermissionDenied(
                    "only channel admins can grant the admin role"
                )
            role = requested_role

        try:
            membership = ChannelService.add_member(
                channel=channel,
                user=target_user,
                added_by=request.user,
                role=role,
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        return Response(
            ChannelMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class ChannelMemberRemoveView(APIView):
    """
    ``DELETE /chat/channels/{cid}/members/{user_id}/``

    Self-leave when ``user_id`` matches the caller; admin-kick otherwise.
    Idempotent: returns 204 even if the user wasn't a member.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, id, user_id):
        channel = _get_workspace_channel(request, id)
        is_self = str(user_id) == str(request.user.id)

        if not is_self:
            caller_membership = _require_channel_membership(request.user, channel)
            if caller_membership.role != ChannelMembership.Role.ADMIN:
                raise PermissionDenied(
                    "channel admin role required to remove other members"
                )

        from donna.users.models import User
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist as exc:
            raise NotFound("target user not found") from exc

        ChannelService.remove_member(
            channel=channel, user=target_user, removed_by=request.user
        )
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

        # Workspace is set by WorkspaceMiddleware from X-Workspace-Id.
        # Always pass it explicitly so the legacy "first overlapping
        # workspace" fallback never fires from REST callers.
        try:
            channel = ChannelService.get_or_create_dm(
                request.user, peer, workspace_id=request.workspace.id
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"peer_user_id": str(exc)}) from exc
        return Response(ChannelSerializer(channel).data)


class GroupDMOpenView(APIView):
    """
    POST /chat/dms/group/ — open or create a group DM (N ≥ 3 distinct
    members). Exact-set-match semantics: an existing group DM with the
    same members is reused.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GroupDMOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        peer_ids = serializer.validated_data["peer_user_ids"]

        from donna.users.models import User
        # Caller is always part of the group.
        all_ids = {str(request.user.id), *(str(p) for p in peer_ids)}
        if len(all_ids) < 2:
            raise ValidationError(
                {"peer_user_ids": "at least one distinct peer required"}
            )
        users = list(User.objects.filter(id__in=all_ids))
        if {str(u.id) for u in users} != all_ids:
            raise NotFound("one or more peers not found")

        try:
            channel = ChannelService.create_group_dm(
                workspace=request.workspace, users=users
            )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValueError as exc:
            raise ValidationError({"peer_user_ids": str(exc)}) from exc
        return Response(ChannelSerializer(channel).data, status=status.HTTP_201_CREATED)


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
