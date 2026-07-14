"""
Chat HTTP REST API.

WS handles realtime push; HTTP handles persistence + history. Frontend
flow: REST loads channel list + history on open, then WS pushes new
events. ``POST /messages`` and WS ``send_message`` both call into the
same ``ChannelService`` so the broadcast path is identical.
"""
from __future__ import annotations

import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ...models import (
    AgentSession,
    Channel,
    ChannelMembership,
    ChannelReadState,
    Artifact,
    Message,
    MessageReaction,
)
from ...services import ChannelService
from .serializers import (
    AddMemberSerializer,
    AdvanceReadSerializer,
    ChannelCreateSerializer,
    ChannelMembershipSerializer,
    ChannelSerializer,
    ChannelUpdateSerializer,
    DMOpenSerializer,
    ArtifactSerializer,
    GroupDMOpenSerializer,
    MessageCreateSerializer,
    MessageEditSerializer,
    MessageSerializer,
    ReactionCreateSerializer,
    ReactionSerializer,
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

        Pass ``?include_public=true`` to also surface public channels
        in the workspace the caller hasn't joined yet (Slack-style
        "browse"). Self-join is then a POST to
        ``/chat/channels/{id}/members/``.

        DMs (kind=DIRECT) are always excluded from the browse path —
        public discovery wouldn't make sense for them.

        Annotates ``_is_pinned`` per-row so the serializer renders
        ``is_pinned`` without N+1 lookups.
        """
        from django.db.models import Exists, OuterRef

        from ...models import ChannelPin

        user = self.request.user
        workspace = self.request.workspace
        include_public = (
            self.request.query_params.get("include_public", "").lower()
            in ("1", "true", "yes")
        )

        base = Channel.objects.filter(workspace=workspace)
        if include_public:
            qs = base.filter(
                Q(memberships__user=user)
                | Q(
                    visibility=Channel.Visibility.PUBLIC,
                    kind=Channel.Kind.CHANNEL,
                )
            )
        else:
            qs = base.filter(memberships__user=user)
        qs = qs.annotate(
            _is_pinned=Exists(ChannelPin.objects.filter(user=user, channel=OuterRef("pk")))
        )
        return qs.distinct().order_by("name")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

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
            modified_by=request.user,
        )
        ChannelMembership.objects.create(
            channel=channel, user=request.user, role=ChannelMembership.Role.ADMIN
        )
        # Public channels are visible to everyone: auto-add every workspace
        # member (idempotent; leaves the creator's ADMIN role intact).
        if channel.visibility == Channel.Visibility.PUBLIC:
            ChannelService.add_all_workspace_members(
                channel=channel, added_by=request.user
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
        members.
        """
        user = self.request.user
        workspace = self.request.workspace
        return Channel.objects.filter(workspace=workspace).filter(
            Q(memberships__user=user)
            | Q(
                visibility=Channel.Visibility.PUBLIC,
                kind=Channel.Kind.CHANNEL,
            )
        ).distinct()

    def _require_admin(self, channel):
        membership = _require_channel_membership(self.request.user, channel)
        if membership.role != ChannelMembership.Role.ADMIN:
            raise PermissionDenied("channel admin role required")

    def partial_update(self, request, *args, **kwargs):
        channel = self.get_object()
        self._require_admin(channel)

        serializer = ChannelUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        was_public = channel.visibility == Channel.Visibility.PUBLIC
        for field, value in serializer.validated_data.items():
            setattr(channel, field, value)
        channel.modified_by = request.user
        channel.save()
        # Flipping private → public exposes the channel to everyone: backfill
        # the roster with all workspace members.
        if not was_public and channel.visibility == Channel.Visibility.PUBLIC:
            ChannelService.add_all_workspace_members(
                channel=channel, added_by=request.user
            )
        ChannelService.emit_channel_updated(channel)
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
        data = serializer.validated_data

        parent = None
        parent_id = data.get("parent_id")
        if parent_id:
            parent = get_object_or_404(Message, id=parent_id, channel=channel)
            # 1-level threading: replies-to-replies collapse to the top.
            if parent.parent_id is not None:
                parent = Message.objects.get(id=parent.parent_id)

        message = ChannelService.send_message(
            channel=channel,
            sender_user=request.user,
            body=data["body"],
            client_msg_id=data.get("client_msg_id"),
            parent=parent,
        )
        return Response(
            MessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


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


# ── Plan 13 §1.5 — answer an AskUserQuestion ────────────────────────────────
class MessageAnswerView(APIView):
    """``POST /chat/messages/{id}/answer`` — resolve a HIL question.

    Body: ``{"value": <picked-value>, "text": "<optional free text>"}``.

    Side effects (atomic):
    1. Writes an ANSWER message child linked via ``answered_message``.
    2. Mirrors the payload onto the parent QUESTION row's
       ``answer_payload`` so the resumer can read it without a join.
    3. Enqueues ``chat.resume_turn`` so the suspended agent loop
       continues from the saved graph state on AgentSession.memory.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        from django.db import transaction
        from django.utils import timezone

        question = get_object_or_404(
            Message,
            id=id,
            channel__workspace=request.workspace,
            kind=Message.Kind.QUESTION,
        )
        if question.answer_payload is not None:
            raise ValidationError("question is already answered")
        if question.expires_at and question.expires_at < timezone.now():
            raise ValidationError("question has expired")

        payload = {
            "value": request.data.get("value"),
            "text": request.data.get("text"),
        }
        with transaction.atomic():
            answer = Message.objects.create(
                channel=question.channel,
                author_user=request.user,
                body=request.data.get("text") or str(payload["value"] or ""),
                kind=Message.Kind.ANSWER,
                answered_message=question,
                answer_payload=payload,
                parent=question.parent_id and question.parent or None,
            )
            # Mirror onto the question row for the resumer's join-free read.
            question.answer_payload = payload
            question.save(update_fields=["answer_payload", "updated_at"])

        # Best-effort resume kick — task lives in chat.tasks.
        try:
            from donna.chat.tasks import resume_turn
            resume_turn.delay(str(question.id))
        except Exception:  # noqa: BLE001 — resume is best-effort here
            pass

        return Response({
            "question_id": str(question.id),
            "answer_id": str(answer.id),
            "answer_payload": payload,
        }, status=status.HTTP_200_OK)


# ── Plan 13 §5.2.2 — channel-resident agent install / uninstall ─────────────
class ChannelAgentInstallView(APIView):
    """``POST /chat/channels/<id>/agents/install/`` — install a resident
    agent under a handle. Body: ``{"handle": "...", "name": "..."}``."""

    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        from donna.chat.models import AgentSession

        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace,
        )
        handle = (request.data.get("handle") or "").strip()
        if not handle:
            raise ValidationError("handle is required")
        display_name = request.data.get("name") or handle.capitalize()
        # Partial-unique enforces uniqueness at the DB layer; surface a
        # clean 400 instead of letting IntegrityError leak.
        if AgentSession.objects.filter(
            channel=channel,
            resident_handle=handle,
            is_channel_resident=True,
        ).exists():
            raise ValidationError(
                f"an agent with handle '{handle}' is already installed in this channel"
            )
        session = AgentSession.objects.create(
            channel=channel,
            name=display_name,
            is_channel_resident=True,
            resident_handle=handle,
        )
        return Response({
            "session_id": str(session.id),
            "handle": handle,
            "name": display_name,
        }, status=status.HTTP_201_CREATED)


class ChannelAgentUninstallView(APIView):
    """``DELETE /chat/channels/<id>/agents/<handle>/``."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, id, handle):
        from donna.chat.models import AgentSession

        channel = get_object_or_404(
            Channel, id=id, workspace=request.workspace,
        )
        try:
            session = AgentSession.objects.get(
                channel=channel,
                resident_handle=handle,
                is_channel_resident=True,
            )
        except AgentSession.DoesNotExist as exc:
            raise NotFound(f"no resident agent '{handle}' in this channel") from exc
        session.delete()
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
            # Self-join only on public channels — private channels require
            # an admin to invite. (GUEST gating is Phase 2.)
            if channel.visibility != Channel.Visibility.PUBLIC:
                raise PermissionDenied(
                    "self-join is only allowed on public channels"
                )
            target_user = request.user
            role = ChannelMembership.Role.MEMBER
        else:
            # Admin-add — caller must hold ADMIN on the channel.
            caller_membership = _require_channel_membership(request.user, channel)
            if caller_membership.role != ChannelMembership.Role.ADMIN:
                raise PermissionDenied(
                    "channel admin role required to add members"
                )
            from donna.users.models import User
            try:
                target_user = User.objects.get(id=target_user_id)
            except User.DoesNotExist as exc:
                raise NotFound("target user not found") from exc
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
    ``PATCH  /chat/channels/{cid}/members/{user_id}/`` — change role (admin only)
    ``DELETE /chat/channels/{cid}/members/{user_id}/`` — remove / self-leave

    Self-leave when ``user_id`` matches the caller; admin-kick otherwise.
    Idempotent: DELETE returns 204 even if the user wasn't a member.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, id, user_id):
        channel = _get_workspace_channel(request, id)
        caller = _require_channel_membership(request.user, channel)
        if caller.role != ChannelMembership.Role.ADMIN:
            raise PermissionDenied("channel admin role required to change roles")
        membership = ChannelService.set_member_role(
            channel=channel, user_id=user_id, role=request.data.get("role"),
        )
        return Response(ChannelMembershipSerializer(membership).data)

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


# ── Artifacts (A2 drafting visibility, 2026-06-21) ─────────────────────────
class ChannelArtifactsView(generics.ListAPIView):
    """``/chat/channels/{id}/artifacts/`` — read-only list.

    Surfaces every Artifact attached to the channel — drafting,
    finalized, abandoned — newest first. Polled by Bruno / frontend to
    inspect draft state as the agent works (the A2 lifecycle has no
    other HTTP surface; ``UpdateDraftSectionTool`` pushes
    ``chat.artifact.updated`` over WS for live UIs).

    Filter via ``?status=drafting`` (or ``finalized``/``abandoned``).
    """

    serializer_class = ArtifactSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        channel = get_object_or_404(
            Channel, id=self.kwargs["id"], workspace=self.request.workspace
        )
        _require_channel_membership(self.request.user, channel)
        qs = Artifact.objects.filter(channel=channel).order_by("-updated_at")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class ChannelArtifactDetailView(generics.RetrieveAPIView):
    """``/chat/channels/{id}/artifacts/{artifact_id}/`` — single Artifact."""

    serializer_class = ArtifactSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "artifact_id"

    def get_queryset(self):
        channel = get_object_or_404(
            Channel, id=self.kwargs["id"], workspace=self.request.workspace
        )
        _require_channel_membership(self.request.user, channel)
        return Artifact.objects.filter(channel=channel)


class WorkspaceArtifactDetailView(generics.RetrieveAPIView):
    """``/chat/artifacts/{artifact_id}/`` — workspace-scoped artifact lookup.

    Used by the right-rail preview pane (Plan 13): a ``doc://<uuid>``
    chip may point at an artifact in a sibling channel, so the
    channel-scoped detail endpoint can't find it. We resolve to any
    artifact in the active workspace where the user is a member of the
    owning channel.
    """

    serializer_class = ArtifactSerializer
    permission_classes = [IsAuthenticated]
    lookup_url_kwarg = "artifact_id"

    def get_queryset(self):
        return Artifact.objects.filter(
            channel__workspace=self.request.workspace,
        )

    def get_object(self):
        obj = super().get_object()
        _require_channel_membership(self.request.user, obj.channel)
        return obj


# ── Pins ────────────────────────────────────────────────────────────────────
class ChannelPinView(APIView):
    """``/chat/channels/{id}/pin/`` — per-user pin / unpin.

    POST  → pin (idempotent)
    DELETE → unpin (idempotent)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        channel = _get_workspace_channel(request, id)
        _require_channel_membership(request.user, channel)
        ChannelService.pin_channel(user=request.user, channel=channel)
        return Response({"pinned": True})

    def delete(self, request, id):
        channel = _get_workspace_channel(request, id)
        _require_channel_membership(request.user, channel)
        ChannelService.unpin_channel(user=request.user, channel=channel)
        return Response({"pinned": False})


# ── Replies (thread view) ───────────────────────────────────────────────────
class MessageRepliesView(APIView):
    """``GET /chat/messages/{id}/replies/`` — flat list of child messages.

    Channel membership required (replies inherit the parent's channel ACL).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        parent = get_object_or_404(
            Message, id=id, channel__workspace=request.workspace
        )
        _require_channel_membership(request.user, parent.channel)

        replies = (
            Message.objects
            .filter(parent=parent)
            .order_by("created_at")
        )
        return Response(
            MessageSerializer(replies, many=True, context={"request": request}).data
        )


# ── Reactions ───────────────────────────────────────────────────────────────
class MessageReactionsView(APIView):
    """``/chat/messages/{id}/reactions/``

    POST   — add reaction (body: ``{emoji}``)
    DELETE — remove own reaction (body: ``{emoji}``)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        message = get_object_or_404(
            Message, id=id, channel__workspace=request.workspace
        )
        _require_channel_membership(request.user, message.channel)

        serializer = ReactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reaction = ChannelService.add_reaction(
                user=request.user,
                message=message,
                emoji=serializer.validated_data["emoji"],
            )
        except ValueError as exc:
            raise ValidationError({"emoji": str(exc)}) from exc
        return Response(ReactionSerializer(reaction).data, status=status.HTTP_201_CREATED)

    def delete(self, request, id):
        message = get_object_or_404(
            Message, id=id, channel__workspace=request.workspace
        )
        _require_channel_membership(request.user, message.channel)

        serializer = ReactionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ChannelService.remove_reaction(
            user=request.user,
            message=message,
            emoji=serializer.validated_data["emoji"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MentionCandidatesView(APIView):
    """
    ``GET /chat/channels/{cid}/mention-candidates/?q=&limit=``

    Union of mention targets for the composer popover:
      - workspace agents on this channel (AgentSession.name)
      - channel members (User)
      - special tokens: everyone, channel, here

    Query is case-insensitive prefix match against name/email/handle.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        channel = _get_workspace_channel(request, id)
        _require_channel_membership(request.user, channel)

        q = (request.query_params.get("q") or "").strip().lower()
        limit = min(int(request.query_params.get("limit") or 20), 50)

        candidates: list[dict] = []

        # Special tokens.
        for token, label in (("everyone", "Everyone"), ("channel", "Channel"), ("here", "Here")):
            if not q or token.startswith(q):
                candidates.append(
                    {"kind": "special", "id": token, "handle": token, "label": label}
                )

        # Agents on this channel.
        agent_qs = AgentSession.objects.filter(channel=channel)
        if q:
            agent_qs = agent_qs.filter(name__icontains=q)
        for a in agent_qs[:limit]:
            candidates.append(
                {"kind": "agent", "id": str(a.id), "handle": a.name.lower(), "label": a.name}
            )

        # Channel members.
        mem_qs = ChannelMembership.objects.select_related("user").filter(channel=channel)
        if q:
            mem_qs = mem_qs.filter(
                Q(user__full_name__icontains=q) | Q(user__email__icontains=q)
            )
        for m in mem_qs[:limit]:
            u = m.user
            display = u.full_name or u.email.split("@")[0]
            candidates.append(
                {
                    "kind": "user",
                    "id": str(u.id),
                    "handle": (u.full_name or u.email.split("@")[0]).lower().replace(" ", ""),
                    "label": display,
                    "email": u.email,
                }
            )

        return Response({"data": candidates[:limit]})
