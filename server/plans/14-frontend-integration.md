# Plan — Frontend integration shipping (8 features)

> Source of decisions: 2026-06-25 chat with Rares.
> Source of current state: `server/donna/chat/models.py`, `server/donna/workspaces/models.py`,
> `web/src/`, `desktop/src/main.ts` (verified 2026-06-25).
> Out of scope: cortex Phase 6, agent runtime maturity (see [13](13-agent-runtime-maturity.md)),
> Nango integration (see [11](11-nango-integration.md)), deployment pipelines (see [12](12-deployment-pipelines.md)).
> Desktop client (`desktop/`) is empty shell; this plan ships against `web/` only.
> Desktop will reuse the same API surface in a future iteration.

---

## Context

### Goal

Ship 8 user-facing features end-to-end so Donna is usable as a daily-driver chat
app, not just an agent runtime. Each feature lands as: backend (model +
migration + serializer + view + tests) + frontend (API client + state slice +
component + wired in) + verification.

### Features + answered design decisions

1. **Pinned channels** — per-user pin/unpin
2. **Emoji reactions** — Slack-style curated ~200 emojis; **bidirectional** (users react to agent + agent reacts to users via tool)
3. **@mentions** — all semantics: `@donna`, `@everyone`, `@channel`, `@user`
4. **Invite to channel** — workspace admin OR channel admin adds workspace members
5. **Invite to workspace** — email-based via **Django templates + Google SMTP**; signed token; accept page
6. **Private DMs** — get-or-create `Channel.Kind.DIRECT` between 2 users
7. **Members chat + reply threading** — polish existing Composer/Message; ship `Message.parent` reply UI
8. **Cowork left panel — documents** — `ChannelDocumentsView` already shipped; build the rail

### Current state (verified 2026-06-25)

**Backend done:**
- `Channel(Kind=CHANNEL|DIRECT)` + `ChannelMembership(Role=ADMIN|MEMBER)`
- `Message(parent FK → self)` — threading model field exists, no UI
- `ChannelReadState`
- `Document` + `ChannelDocumentsView` (DRF)
- `Workspace` + `WorkspaceMembership`
- Notifications app (DB + SSE)
- WS realtime (Channels) — `channel_group`, `channel_typing_group`, `agent_run_group`

**Web frontend exists (React + Vite + Tailwind + Zustand):**
- Views: Auth, Channel, Personal, WorkspacePicker, Integrations, OAuthReturn, Showcase, ComingSoon
- Shell: AppShell, Sidebar, TopBar, WsRail, RightRailSlot, ToastStack
- Channel: ChannelHeader, Composer, Message, CreateChannelDialog
- State: auth, channels, messages, notifications, presence, integrations, workspace
- API: auth, chat, client, integrations, notifications, workspaces

### Plan shape

8 phases, dependency-ordered. Each independently shippable. Total ≈ 11.5d.

| Phase | Feature | Effort | Why this order |
|---|---|---|---|
| P0 | Private DMs | ~1.5d | Unblocks DM sidebar section; reused by P3, P5 patterns |
| P1 | Chat polish + reply threading | ~1.5d | Baseline UX before adding bells |
| P2 | Pinned channels | ~1d | Small win; visible immediately in Sidebar |
| P3 | Cowork docs left panel | ~0.5d | Backend done; pure frontend |
| P4 | Invite to channel | ~1d | Small backend + small frontend |
| P5 | Invite to workspace | ~2d | Biggest scope (email + accept page + signed token) |
| P6 | @mentions (all 4 semantics) | ~2d | Needs notifications wiring |
| P7 | Emoji reactions (peer-to-peer) + inline emoji insertion | ~2d | Shared EmojiPicker serves both reactions + composer |

---

## P0 — Private DMs (~1.5d)

**Goal:** users can start a 1-to-1 DM with any workspace member.

### P0.1 Backend

**Service:** `chat/services.py:ChatService.get_or_create_dm(*, current_user, other_user_id)`

```python
def get_or_create_dm(self, *, current_user, other_user_id) -> Channel:
    """Idempotent get-or-create of a 2-person DIRECT channel.

    Naming: sorted (user_a_id, user_b_id) tuple stored on Channel.metadata
    so lookup is deterministic. Self-DM (a==b) raises ValidationError.
    """
    from donna.workspaces.models import WorkspaceMembership

    if str(current_user.id) == str(other_user_id):
        raise ValidationError("cannot DM yourself")

    other = (
        WorkspaceMembership.objects
        .filter(workspace=self.company, user_id=other_user_id)
        .select_related("user").first()
    )
    if other is None:
        raise NotFound("other user not in workspace")

    pair = tuple(sorted([str(current_user.id), str(other.user_id)]))
    metadata_key = "|".join(pair)

    existing = (
        Channel.objects
        .filter(workspace=self.company, kind=Channel.Kind.DIRECT)
        .filter(metadata__dm_pair=metadata_key)
        .first()
    )
    if existing:
        return existing

    with transaction.atomic():
        channel = Channel.objects.create(
            workspace=self.company,
            kind=Channel.Kind.DIRECT,
            visibility=Channel.Visibility.PRIVATE,  # required by CheckConstraint
            name="",                                 # rendered client-side as "other user"
            metadata={"dm_pair": metadata_key},
            created_by=current_user,
        )
        ChannelMembership.objects.bulk_create([
            ChannelMembership(channel=channel, user=current_user,  role=ChannelMembership.Role.MEMBER),
            ChannelMembership(channel=channel, user=other.user,    role=ChannelMembership.Role.MEMBER),
        ])
    return channel
```

**Migration:** none — `metadata` JSONField already exists on `Channel`.

**Add field if missing:** verify `Channel.metadata = models.JSONField(default=dict)` exists; if not, add migration.

**View:** `chat/api/v1/views.py`
```python
class DirectMessageView(APIView):
    permission_classes = [IsAuthenticated]
    service_class = ChatService

    def post(self, request):
        serializer = StartDMSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = self.get_service().get_or_create_dm(
            current_user=request.user,
            other_user_id=serializer.validated_data["user_id"],
        )
        return Response(ChannelSerializer(channel).data, status=200)
```

**Serializer:** `StartDMSerializer(user_id: UUIDField)`.

**URL:** `path("dm/", DirectMessageView.as_view(), name="start-dm")`.

**Channel list filter:** `ChannelViewSet` gains `?kind=channel|direct` filter so frontend can split sections.

**Tests:** `chat/tests/test_dm.py` — get-or-create idempotent, self-DM rejected, cross-workspace rejected, DIRECT kind asserts PRIVATE visibility via existing CheckConstraint.

### P0.2 Frontend

**API client:** `web/src/api/chat.ts`
```typescript
export async function startDM(otherUserId: string): Promise<Channel> {
  return apiPost("/api/v1/chat/dm/", { user_id: otherUserId });
}

export async function listChannels(kind?: "channel" | "direct"): Promise<Channel[]> {
  const qs = kind ? `?kind=${kind}` : "";
  return apiGet(`/api/v1/chat/channels/${qs}`);
}
```

**Zustand slice:** `web/src/state/channels.ts` gains `dms: Channel[]` separate from `channels`.

**Component:** `web/src/components/Channel/StartDMDialog.tsx` — workspace member picker.

**Sidebar:** `web/src/components/Shell/Sidebar.tsx` adds DM section under Channels:
```tsx
<section>
  <header className="flex items-center justify-between">
    <span>Direct Messages</span>
    <button onClick={() => setStartDMOpen(true)}>+</button>
  </header>
  {dms.map(c => <DMRow key={c.id} channel={c} />)}
</section>
```

**Display name resolver:** DM channels render as `other user's display name`. Helper:
```typescript
export function dmDisplayName(channel: Channel, currentUserId: string): string {
  const members = channel.members ?? [];
  const other = members.find(m => m.user.id !== currentUserId);
  return other?.user.display_name ?? "Unknown";
}
```

### P0.3 Verification

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.chat.tests.test_dm -v 2"
# Bruno: POST /api/v1/chat/dm/ {user_id: <other-uuid>} → 200 Channel
# Bruno: POST /api/v1/chat/dm/ {user_id: <same other>} → 200 SAME channel id
```

---

## P1 — Chat polish + reply threading (~1.5d)

**Goal:** existing chat feels solid; `Message.parent` shows as threaded replies.

### P1.1 Backend

**Verify:** `Message.parent` FK to self with `related_name="replies"` exists. Add if missing.

**Serializer:** `MessageSerializer` adds `reply_count` (annotated via subquery) + `parent_id`.

**View:** `MessageViewSet` action `replies` — `GET /messages/<id>/replies/` returns child messages ordered by `created_at`.

**WS event:** existing `chat.message.created` already broadcasts; ensure payload includes `parent_id` so frontend routes to thread vs channel.

### P1.2 Frontend

**Chat polish:**
- Auto-scroll to bottom on new own message (always); on incoming message only when already near bottom (avoid jump-stealing).
- Infinite scroll upward — `IntersectionObserver` on top sentinel, fetch older `?before=<msg_id>`.
- Persist scroll position across re-renders via `scrollRestoration` ref.
- Typing indicators: WS `chat.typing.started/stopped` from `channel_typing_group` (already broadcast by Composer keystrokes).
- ChannelReadState: on message visibility (IntersectionObserver), debounced `PATCH /channels/<id>/read-state/` with `last_read_message_id`.

**Threading:**
- `Message.tsx` gains "Reply" button on hover.
- Click opens `<ThreadPanel/>` in RightRailSlot showing parent message + child messages list.
- ThreadPanel has own composer; sends with `parent_id: <parent uuid>`.
- Thread reply count chip rendered under message in main channel.
- WS handler: incoming message w/ `parent_id` only appends in ThreadPanel + bumps reply count chip in channel.

**New component:** `web/src/components/Channel/ThreadPanel.tsx`.

**State slice:** `web/src/state/messages.ts` gains `threads: Record<channelId, Record<parentId, Message[]>>`.

### P1.3 Verification

- Type-then-scroll-up: composer doesn't jump.
- Send message: auto-scrolls to own.
- Receive message while scrolled up: NO scroll-steal; toast "New message ↓".
- Reply on a message: opens ThreadPanel; reply persists; main channel shows "3 replies" chip.

---

## P2 — Pinned channels (~1d)

**Goal:** per-user pin/unpin; Sidebar Pinned section above Channels.

### P2.1 Backend

**New model:** `chat/models.py`
```python
class ChannelPin(TimestampsMixin):
    """Per-user pinned channel marker."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_pins",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="pins",
    )

    class Meta:
        db_table = "chat_channel_pins"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "channel"],
                name="uq_channel_pin_user_channel",
            ),
        ]
        indexes = [models.Index(fields=["user"])]
```

**Migration:** `0005_channelpin.py`.

**Endpoints:** add to `ChannelViewSet`:
```python
@action(detail=True, methods=["post", "delete"], url_path="pin")
def pin(self, request, pk=None):
    channel = self.get_object()
    if request.method == "POST":
        ChannelPin.objects.get_or_create(user=request.user, channel=channel)
        return Response({"pinned": True})
    ChannelPin.objects.filter(user=request.user, channel=channel).delete()
    return Response({"pinned": False})
```

**Serializer:** `ChannelSerializer.is_pinned` annotated via `Subquery` over the request user.

### P2.2 Frontend

**API client:** `chat.ts` gains `pinChannel(id)` / `unpinChannel(id)`.

**State:** `channels.ts` slice annotates `is_pinned` on each channel; computed selector `pinnedChannels` / `unpinnedChannels`.

**Sidebar:** new section above Channels:
```tsx
{pinned.length > 0 && (
  <section>
    <header>Pinned</header>
    {pinned.map(c => <ChannelRow channel={c} />)}
  </section>
)}
<section>
  <header>Channels</header>
  {unpinned.map(c => <ChannelRow channel={c} />)}
</section>
```

**Context menu:** Channel right-click / "⋮" → Pin / Unpin action.

### P2.3 Verification

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.chat.tests.test_pins -v 2"
```
Pin → Sidebar Pinned section appears with channel. Unpin → channel moves back to Channels.

---

## P3 — Cowork docs left panel (~0.5d)

**Goal:** channel left/right panel lists active drafts + finalized docs; click → preview.

### P3.1 Backend

Done. `ChannelDocumentsView` returns `?status=drafting` filter. WS event `chat.document.updated` already broadcasts on `update_draft_section`.

### P3.2 Frontend

**API client:** `chat.ts`
```typescript
export async function listChannelDocuments(channelId: string, status?: string) {
  const qs = status ? `?status=${status}` : "";
  return apiGet(`/api/v1/chat/channels/${channelId}/documents/${qs}`);
}
```

**State slice:** `web/src/state/documents.ts` (NEW)
```typescript
export const useDocumentsStore = create((set) => ({
  byChannel: {} as Record<string, Document[]>,
  load: async (channelId: string) => {
    const docs = await listChannelDocuments(channelId);
    set(state => ({ byChannel: { ...state.byChannel, [channelId]: docs } }));
  },
  onWsDocumentUpdated: (channelId: string, doc: Document) => {
    set(state => {
      const list = state.byChannel[channelId] ?? [];
      const idx = list.findIndex(d => d.id === doc.id);
      const next = idx >= 0 ? list.with(idx, doc) : [doc, ...list];
      return { byChannel: { ...state.byChannel, [channelId]: next } };
    });
  },
}));
```

**Component:** `web/src/components/Channel/DocumentsRail.tsx`
- Two sub-sections: "Drafting" + "Finalized" (last 5).
- Each row: title, version badge, status pill, updated timestamp.
- Click → open `<DocumentPreview/>` modal with markdown body (use existing markdown renderer).

**Mount:** in `views/Channel.tsx` left or right of Composer, behind a toggle button.

**WS wiring:** `web/src/lib/ws.ts` (or wherever socket events route) — on `chat.document.updated`, call `useDocumentsStore.getState().onWsDocumentUpdated(channelId, doc)`.

### P3.3 Verification

- Send chat message: "draft me a status update for Acme".
- DocumentsRail shows draft v1 → v2 → v3 live as agent edits.

---

## P4 — Invite to channel (~1d)

**Goal:** admins add workspace members to channel.

### P4.1 Backend

**Permission helper:** `chat/permissions.py:can_manage_channel_members(user, channel)`:
```python
def can_manage_channel_members(user, channel) -> bool:
    """True if user is channel admin OR workspace admin."""
    if ChannelMembership.objects.filter(
        channel=channel, user=user, role=ChannelMembership.Role.ADMIN,
    ).exists():
        return True
    if WorkspaceMembership.objects.filter(
        workspace=channel.workspace, user=user,
        role__in=[WorkspaceMembership.Role.ADMIN, WorkspaceMembership.Role.OWNER],
    ).exists():
        return True
    return False
```

**Endpoints:** add to `ChannelViewSet`:
```python
@action(detail=True, methods=["post"], url_path="members")
def add_member(self, request, pk=None):
    channel = self.get_object()
    if not can_manage_channel_members(request.user, channel):
        raise PermissionDenied
    serializer = AddMemberSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user_id = serializer.validated_data["user_id"]
    role = serializer.validated_data.get("role", ChannelMembership.Role.MEMBER)

    # Must already be in workspace
    if not WorkspaceMembership.objects.filter(
        workspace=channel.workspace, user_id=user_id,
    ).exists():
        raise ValidationError("user not in workspace")

    membership, created = ChannelMembership.objects.get_or_create(
        channel=channel, user_id=user_id, defaults={"role": role},
    )
    _broadcast_member_added(channel, membership)
    return Response(ChannelMembershipSerializer(membership).data, status=201 if created else 200)


@action(detail=True, methods=["delete"], url_path="members/(?P<user_id>[^/.]+)")
def remove_member(self, request, pk=None, user_id=None):
    channel = self.get_object()
    if not can_manage_channel_members(request.user, channel):
        raise PermissionDenied
    deleted, _ = ChannelMembership.objects.filter(
        channel=channel, user_id=user_id,
    ).delete()
    _broadcast_member_removed(channel.id, user_id)
    return Response(status=204)
```

**WS event:** `chat.member.added` / `chat.member.removed` on `channel_group`.

### P4.2 Frontend

**Component:** `web/src/components/Channel/InviteToChannelDialog.tsx`
- Workspace member picker (filtered to NOT-in-channel)
- Submit → POST /members/ → close

**Trigger:** ChannelHeader.tsx gets "Members" button → opens dialog with current member list + add/remove actions (if admin).

**WS:** on `chat.member.added`/`chat.member.removed`, update channel member list in state.

### P4.3 Verification

- Channel admin clicks "Add member" → picks user → user appears in channel members → user's Sidebar shows the new channel.

---

## P5 — Invite to workspace (~2d)

**Goal:** email-based workspace invitations via Django templates + Google SMTP.

### P5.1 Settings — Google SMTP

**Edit:** `donna/settings.py` (or `settings/base.py` after [12](12-deployment-pipelines.md)):
```python
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")  # Gmail App Password (not account password)
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="Donna <noreply@donna.ai>")
```

**`.env.example`:**
```
EMAIL_HOST_USER=donna-sender@workspace.com
EMAIL_HOST_PASSWORD=<16-char-app-password>     # NOT account password; create at myaccount.google.com/apppasswords
DEFAULT_FROM_EMAIL=Donna <donna-sender@workspace.com>
```

Note: production Google SMTP cap = 500/day (free) or 2000/day (Workspace). Long-term: migrate to SES / SendGrid. Document in plan.

### P5.2 Backend

**New model:** `workspaces/models.py`
```python
class WorkspaceInvitation(TimestampsMixin):
    """Email-based workspace invite.

    Token signed via Django's signing module + per-row UUID secret so
    revoking is one-row delete.
    """
    class Status(models.TextChoices):
        PENDING  = "pending",  "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED  = "revoked",  "Revoked"
        EXPIRED  = "expired",  "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_invitations")
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=WorkspaceMembership.Role.choices, default=WorkspaceMembership.Role.MEMBER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="accepted_invitations",
    )

    class Meta:
        db_table = "workspace_invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "email"],
                condition=models.Q(status="pending"),
                name="uq_pending_invitation_per_email_workspace",
            ),
        ]
        indexes = [
            models.Index(fields=["email", "status"]),
            models.Index(fields=["expires_at"]),
        ]
```

**Migration.**

**Service:** `workspaces/services.py:WorkspaceService.create_invitation(workspace, email, role)`:
```python
from datetime import timedelta
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone


_INVITE_SALT = "donna.workspaces.invitation"
_INVITE_MAX_AGE = 14 * 24 * 3600  # 14 days


def create_invitation(self, *, workspace, email, role="member") -> WorkspaceInvitation:
    # Revoke any existing pending invite for the same (workspace, email)
    WorkspaceInvitation.objects.filter(
        workspace=workspace, email=email, status=WorkspaceInvitation.Status.PENDING,
    ).update(status=WorkspaceInvitation.Status.REVOKED)

    invite = WorkspaceInvitation.objects.create(
        workspace=workspace,
        invited_by=self.current_user,
        email=email,
        role=role,
        expires_at=timezone.now() + timedelta(seconds=_INVITE_MAX_AGE),
    )
    token = signing.dumps({"id": str(invite.id)}, salt=_INVITE_SALT)
    self._send_email(invite, token)
    return invite


def _send_email(self, invite, token):
    accept_url = f"{settings.FRONTEND_BASE_URL}/invitations/{token}/accept"
    ctx = {
        "workspace_name": invite.workspace.name,
        "invited_by": invite.invited_by.display_name or invite.invited_by.email,
        "accept_url": accept_url,
        "expires_at": invite.expires_at,
    }
    subject = f"You're invited to join {invite.workspace.name} on Donna"
    html_body = render_to_string("workspaces/emails/invitation.html", ctx)
    text_body = render_to_string("workspaces/emails/invitation.txt", ctx)
    send_mail(
        subject=subject,
        message=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invite.email],
        html_message=html_body,
    )


@classmethod
def verify_token(cls, token: str) -> WorkspaceInvitation:
    try:
        data = signing.loads(token, salt=_INVITE_SALT, max_age=_INVITE_MAX_AGE)
    except signing.BadSignature as exc:
        raise ValidationError("invalid or expired invitation token") from exc
    invite = WorkspaceInvitation.objects.get(id=data["id"])
    if invite.status != WorkspaceInvitation.Status.PENDING:
        raise ValidationError(f"invitation is {invite.status}")
    if invite.expires_at < timezone.now():
        invite.status = WorkspaceInvitation.Status.EXPIRED
        invite.save(update_fields=["status", "updated_at"])
        raise ValidationError("invitation expired")
    return invite


@transaction.atomic
def accept_invitation(self, *, token: str, accepting_user) -> WorkspaceMembership:
    invite = self.verify_token(token)
    if accepting_user.email.lower() != invite.email.lower():
        raise ValidationError("invitation email does not match logged-in user")
    membership, _ = WorkspaceMembership.objects.get_or_create(
        workspace=invite.workspace, user=accepting_user,
        defaults={"role": invite.role},
    )
    invite.status = WorkspaceInvitation.Status.ACCEPTED
    invite.accepted_at = timezone.now()
    invite.accepted_by = accepting_user
    invite.save(update_fields=["status", "accepted_at", "accepted_by", "updated_at"])
    return membership
```

**Email templates:** `workspaces/templates/workspaces/emails/invitation.{html,txt}`

```html
<!-- invitation.html -->
<!DOCTYPE html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 40px auto; color: #1a1a1a;">
  <h1 style="font-size: 24px;">You're invited to {{ workspace_name }}</h1>
  <p>{{ invited_by }} has invited you to join the <strong>{{ workspace_name }}</strong> workspace on Donna.</p>
  <p><a href="{{ accept_url }}" style="display: inline-block; padding: 12px 24px; background: #1a1a1a; color: #fff; text-decoration: none; border-radius: 6px;">Accept invitation</a></p>
  <p style="color: #666; font-size: 14px;">This link expires on {{ expires_at|date:"F j, Y" }}. If you weren't expecting this, you can safely ignore it.</p>
</body></html>
```

```
You're invited to {{ workspace_name }}

{{ invited_by }} has invited you to join the {{ workspace_name }} workspace on Donna.

Accept the invitation here:
{{ accept_url }}

This link expires on {{ expires_at|date:"F j, Y" }}.
```

**Service methods follow ServiceMethodMixin convention** so ViewSet auto-discovers
them (`create_workspaceinvitation`, `delete_workspaceinvitation`):

```python
# workspaces/services.py — add to WorkspaceService
def create_workspaceinvitation(self, *, email: str, role: str = "member", **_) -> WorkspaceInvitation:
    """Auto-discovered by ServiceMethodMixin for InvitationViewSet.create."""
    return self.create_invitation(workspace=self.company, email=email, role=role)


def delete_workspaceinvitation(self, instance: WorkspaceInvitation) -> None:
    """Auto-discovered by ServiceMethodMixin for InvitationViewSet.destroy.

    Revoke (not hard-delete) so accept attempts still see status=revoked.
    """
    instance.status = WorkspaceInvitation.Status.REVOKED
    instance.save(update_fields=["status", "updated_at"])
```

**ViewSets** (per [03-conventions-and-api.md](03-conventions-and-api.md) — ModelViewSet + `@action` for non-CRUD):

```python
# workspaces/api/v1/views.py
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from donna.core.viewsets import GenericViewSet, ModelViewSet

from ...models import WorkspaceInvitation
from ...services import WorkspaceService
from .serializers import (
    InvitationSerializer,
    InvitationInspectSerializer,
)


class InvitationViewSet(ModelViewSet):
    """Workspace-tenanted invitation management.

    Lives under the workspace-header middleware — request.workspace is set.
    Routes (default DRF):
      GET    /api/v1/workspaces/invitations/         list pending
      POST   /api/v1/workspaces/invitations/         create + send email
      GET    /api/v1/workspaces/invitations/<id>/    retrieve one
      DELETE /api/v1/workspaces/invitations/<id>/    revoke
    """
    serializer_class = InvitationSerializer
    service_class = WorkspaceService
    permission_classes = [IsAuthenticated]
    # PATCH/PUT not exposed — invitations are immutable; revoke + recreate instead.
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return self.request.workspace.invitations.filter(
            status=WorkspaceInvitation.Status.PENDING,
        )


class PublicInvitationViewSet(GenericViewSet):
    """Public token-based operations — bypasses workspace header tenancy.

    Routes:
      GET  /api/v1/invitations/<token>/         retrieve (no auth) — preview
      POST /api/v1/invitations/<token>/accept/  accept (authed)    — create membership
    """
    permission_classes = [AllowAny]
    authentication_classes: list = []
    lookup_field = "token"
    lookup_value_regex = "[^/]+"

    def retrieve(self, request, token=None):
        try:
            invite = WorkspaceService.verify_token(token)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        return Response(InvitationInspectSerializer(invite).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[IsAuthenticated],
        authentication_classes=None,  # falls back to project default
    )
    def accept(self, request, token=None):
        service = WorkspaceService(current_user=request.user, company=None)
        try:
            membership = service.accept_invitation(token=token, accepting_user=request.user)
        except ValidationError as exc:
            return Response(
                {"detail": str(getattr(exc, "message", exc))},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return Response({"workspace_id": str(membership.workspace_id)}, status=http_status.HTTP_200_OK)
```

**Routers** (per Donna convention — `DefaultRouter` registration):

```python
# workspaces/api/v1/urls.py
from rest_framework.routers import DefaultRouter

from .views import InvitationViewSet, PublicInvitationViewSet


router = DefaultRouter()
router.register(r"invitations", InvitationViewSet, basename="invitation")

public_router = DefaultRouter()
public_router.register(r"invitations", PublicInvitationViewSet, basename="public-invitation")

urlpatterns = [
    *router.urls,           # mounted under /api/v1/workspaces/  (header-tenanted)
]

public_urlpatterns = [
    *public_router.urls,    # mounted under /api/v1/             (no header required)
]
```

**Root URL wire-up** — `donna/urls.py` includes the public router separately:
```python
path("api/v1/workspaces/", include("donna.workspaces.api.v1.urls")),
# Public — bypasses WorkspaceMiddleware via IGNORED_PATHS
path("api/v1/", include(("donna.workspaces.api.v1.urls", "workspaces_public"),
                       namespace="workspaces_public_invitations")),  # only public_urlpatterns mount here
```

Cleaner alternative — put public viewset in a sibling module (`api/v1/public.py`)
and include each with its own router so URL trees don't share namespace. Pick at
implementation time.

**Serializers** (per Donna pattern — separate read / write / inspect):

```python
# workspaces/api/v1/serializers.py
from rest_framework import serializers

from ...models import WorkspaceInvitation


class InvitationSerializer(serializers.ModelSerializer):
    """Workspace-scoped (admin sees pending invites)."""
    class Meta:
        model = WorkspaceInvitation
        fields = [
            "id", "email", "role", "status",
            "invited_by", "expires_at", "accepted_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "invited_by", "expires_at", "accepted_at",
            "created_at", "updated_at",
        ]


class InvitationInspectSerializer(serializers.ModelSerializer):
    """Public preview — strip everything sensitive.

    No invitation id (use signed token), no status/dates beyond expires_at,
    no invited_by user id (only display string).
    """
    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    invited_by = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceInvitation
        fields = ["workspace_name", "email", "invited_by", "expires_at"]
        read_only_fields = fields

    def get_invited_by(self, obj):
        u = obj.invited_by
        return getattr(u, "display_name", None) or u.email
```

**`ServiceMethodMixin` discovery note** — the mixin in `donna/core/mixins.py`
looks up `create_<model_lowercase>` / `delete_<model_lowercase>` by the
serializer's `Meta.model.__name__.lower()`. Hence the verbose service method
names (`create_workspaceinvitation`); name them to match exactly.

**Path bypass** (header-tenanted middleware):
```python
IGNORED_PATHS += ["/api/v1/workspaces/invitations/"]  # public + token-signed
```

### P5.3 Frontend

**API client:** `web/src/api/workspaces.ts`
```typescript
export async function createInvitation(email: string, role = "member") {
  return apiPost("/api/v1/workspaces/invitations/", { email, role });
}
export async function inspectInvitation(token: string) {
  return apiGet(`/api/v1/workspaces/invitations/${token}/`);  // public, no auth header
}
export async function acceptInvitation(token: string) {
  return apiPost(`/api/v1/workspaces/invitations/${token}/accept/`, {});
}
```

**Component:** `web/src/components/Shell/InviteToWorkspaceDialog.tsx` — opens from TopBar settings menu.

**New view:** `web/src/views/AcceptInvitation.tsx` — public route `/invitations/:token/accept`:
- On mount: `inspectInvitation(token)` to render preview ("You've been invited to X by Y").
- If not logged in: redirect to `/auth?return=/invitations/<token>/accept`.
- If logged in with matching email: button "Accept" → `acceptInvitation(token)` → redirect to `/?workspace=<id>`.
- If logged in with WRONG email: "Log out + log in with <invited email>".

**Router:** `web/src/App.tsx` adds route:
```tsx
<Route path="/invitations/:token/accept" element={<AcceptInvitation/>} />
```

### P5.4 Verification

```bash
# Set env vars
export EMAIL_HOST_USER=<gmail-account>
export EMAIL_HOST_PASSWORD=<16-char-app-password>
docker compose restart server

# Backend test
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.workspaces.tests.test_invitation -v 2"
```

Smoke: create invitation via Bruno → check Gmail inbox → click link → accept page renders → log in → membership created.

---

## P6 — @mentions (~2d)

**Goal:** parse `@user` `@donna` `@channel` `@everyone` from message body, store, notify.

### P6.1 Backend

**Migration:** add to `Message`:
```python
mentions = models.ManyToManyField(
    settings.AUTH_USER_MODEL,
    related_name="message_mentions",
    blank=True,
)
mention_flags = models.JSONField(
    default=dict, blank=True,
    help_text="Special mentions: {donna: bool, channel: bool, everyone: bool}.",
)
```

**Parser:** `chat/mentions.py` (NEW — chat infrastructure, NOT agent code)

Mentions are a general chat feature. Any message can have them. `@donna` is
**syntactic sugar** that:
1. Triggers the channel's agent dispatch (same code path as a DM to the agent).
2. Persists the mentioning message into the agent's long-term memory so the
   agent has context about what's been asked of it historically.

The parser belongs in `chat/` proper — `chat/agents/` is for the agent runtime
(prompts, tools, nodes, graph). Mentions are upstream of all that.

```python
"""Mention parser — general chat infrastructure.

Body conventions:
- @<handle>     → User (mention.users)
- @donna        → mention_flags["donna"] = True
                  Triggers agent dispatch + memory persistence (handled in
                  ChatService.create_message, not here).
- @channel      → mention_flags["channel"] = True
- @everyone     → mention_flags["everyone"] = True

Handles are User.handle (introduce if missing; fall back to email prefix).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from donna.chat.models import Channel
    from donna.users.models import User


_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_\.\-]+)")
SPECIAL = {"donna", "channel", "everyone"}


def parse(body: str, channel: "Channel") -> tuple[list["User"], dict[str, bool]]:
    from donna.users.models import User

    handles = {m.group(1).lower() for m in _MENTION_RE.finditer(body)}
    flags = {k: (k in handles) for k in SPECIAL}
    user_handles = handles - SPECIAL
    if not user_handles:
        return [], flags

    users = list(
        User.objects.filter(
            workspace_memberships__workspace=channel.workspace,
            handle__in=user_handles,
        ).distinct()
    )
    return users, flags
```

**Hook into Message save:** `chat/services.py:ChatService.create_message(...)`:
```python
def create_message(self, *, channel, author_user=None, author_agent=None, body, parent=None, **extra):
    msg = Message.objects.create(
        channel=channel, body=body, author_user=author_user, author_agent=author_agent, parent=parent, **extra,
    )
    from donna.chat.mentions import parse as parse_mentions
    users, flags = parse_mentions(body, channel)
    if users:
        msg.mentions.set(users)
    if any(flags.values()):
        msg.mention_flags = flags
        msg.save(update_fields=["mention_flags", "updated_at"])
    _fanout_mention_notifications(msg, users, flags)
    if flags.get("donna"):
        _record_agent_mention(msg, channel)
    return msg


def _fanout_mention_notifications(message, users, flags):
    from donna.notifications.services import NotificationService
    svc = NotificationService()

    recipients = set(u.id for u in users)

    if flags.get("everyone"):
        # All workspace members except author
        recipients.update(
            WorkspaceMembership.objects
            .filter(workspace=message.channel.workspace)
            .exclude(user_id=message.author_user_id)
            .values_list("user_id", flat=True)
        )
    elif flags.get("channel"):
        # All channel members except author
        recipients.update(
            ChannelMembership.objects
            .filter(channel=message.channel)
            .exclude(user_id=message.author_user_id)
            .values_list("user_id", flat=True)
        )

    for user_id in recipients:
        svc.create(user_id=user_id, kind="mention", payload={
            "channel_id": str(message.channel_id),
            "message_id": str(message.id),
            "preview": message.body[:140],
        })


def _record_agent_mention(message, channel):
    """@donna handling — two side effects:

    1. Append the mention to AgentSession.memory['mentions'] as a durable
       trail of "what the user has asked of me historically". The agent's
       state builder picks this up at turn time (Phase 4 of [13]).
    2. Dispatch the agent if the channel wouldn't have dispatched anyway.
       DM channels with Donna already auto-dispatch on every message; group
       channels with Donna as a member dispatch only on @mention.
    """
    from donna.chat.models import AgentSession
    from donna.chat.tasks import run_agent_turn

    session = AgentSession.objects.filter(channel=channel).first()
    if session is not None:
        memory = session.memory or {}
        mentions = list(memory.get("mentions") or [])
        mentions.append({
            "message_id":    str(message.id),
            "author_user_id": str(message.author_user_id) if message.author_user_id else None,
            "body_preview":  message.body[:500],
            "at":            message.created_at.isoformat(),
        })
        # Keep last 50 — older mentions consolidated by AutoDream in [13] Phase 4.
        memory["mentions"] = mentions[-50:]
        session.memory = memory
        session.save(update_fields=["memory", "updated_at"])

    # Dispatch the agent. Idempotent — run_agent_turn checks turn_lock.
    run_agent_turn.delay(str(channel.id), str(message.id))
```

**User.handle:** add field if missing.
```python
# users/models.py
class User(...):
    handle = models.CharField(max_length=40, unique=True, null=True, blank=True)
```

Migration + backfill (`handle = email.split('@')[0]`, deduped with `-2` suffix on collision).

**Serializer:** `MessageSerializer` returns `mentions: [user_id]` + `mention_flags`.

### P6.2 Frontend

**Composer mention autocomplete:** `web/src/components/Channel/Composer.tsx`

```typescript
// On @ keypress: show dropdown with members + @donna + @channel + @everyone.
// Filter by handle prefix as user types.
// Tab/Enter inserts @handle into body.
```

Use a contentEditable + tribute.js / or roll your own popover keyed on cursor position.

**Mention chip rendering:** `web/src/components/Channel/Message.tsx` — replace `@handle` occurrences with styled `<span class="mention">@handle</span>` (regex split on render).

**Special chip colors:**
- `@donna` — purple
- `@channel` — orange
- `@everyone` — red
- `@user` — blue

**Mention badge in Sidebar:** existing notifications state already feeds a count; ensure mention notifications route into per-channel unread badge.

### P6.3 Verification

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.chat.tests.test_mentions -v 2"
```

Smoke: send "hey @alice can you review @donna's draft?" → alice gets notification + donna agent dispatched.

---

## P7 — Emoji reactions + inline emoji picker (~2d)

**Goal:** users react to messages (peer-to-peer; agent does NOT react). Users
can also insert emoji inline in their message body via the same picker.

Two distinct surfaces, one shared picker:
- **Reactions** — hover button on any message → picker → emoji attaches as
  `MessageReaction` row. Reaction bar under message.
- **Inline insertion** — emoji button in Composer → picker → emoji char gets
  inserted at cursor position in message body.

### P7.1 Backend

**New model:** `chat/models.py` — user-only authorship (no agent FK).

```python
class MessageReaction(TimestampsMixin):
    """User → message reaction. Peer-to-peer only — agents do NOT react."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    emoji = models.CharField(max_length=64)   # short code: "thumbsup", "heart", etc
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )

    class Meta:
        db_table = "chat_message_reactions"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "emoji", "author_user"],
                name="uq_reaction_user_message_emoji",
            ),
        ]
        indexes = [
            models.Index(fields=["message", "emoji"]),
        ]
```

**Migration.**

**Curated emoji set:** `chat/emojis.py` (NOT under `agents/` — used by chat
infra, not by any agent tool)
```python
"""Curated Slack-style emoji set — ~200 entries.

Single source of truth for:
- frontend EmojiPicker (reactions + inline insertion)
- backend MessageReaction.emoji validation
Agents do NOT use this — they don't react.
Format: {code: {unicode, group, keywords[]}}.
"""
CURATED_EMOJIS: dict[str, dict] = {
    "thumbsup":   {"unicode": "👍",  "group": "people",  "keywords": ["yes", "ok", "agree"]},
    "thumbsdown": {"unicode": "👎",  "group": "people",  "keywords": ["no", "disagree"]},
    "heart":      {"unicode": "❤️",  "group": "people",  "keywords": ["love"]},
    "fire":       {"unicode": "🔥",  "group": "objects", "keywords": ["hot", "lit"]},
    "tada":       {"unicode": "🎉",  "group": "objects", "keywords": ["party", "celebrate"]},
    "rocket":     {"unicode": "🚀",  "group": "objects", "keywords": ["launch", "ship"]},
    "eyes":       {"unicode": "👀",  "group": "people",  "keywords": ["looking", "watch"]},
    "thinking":   {"unicode": "🤔",  "group": "people",  "keywords": ["hmm"]},
    "checkmark":  {"unicode": "✅",  "group": "symbols", "keywords": ["done", "yes"]},
    "x":          {"unicode": "❌",  "group": "symbols", "keywords": ["no", "wrong"]},
    "warning":    {"unicode": "⚠️",  "group": "symbols", "keywords": ["caution"]},
    "bulb":       {"unicode": "💡",  "group": "objects", "keywords": ["idea"]},
    # ... ~200 entries
}
```

**ViewSet** (Donna convention — ModelViewSet via nested route under MessageViewSet):

```python
# chat/api/v1/views.py
from rest_framework.decorators import action

from donna.chat.emojis import CURATED_EMOJIS
from donna.core.viewsets import ModelViewSet


class ReactionViewSet(ModelViewSet):
    """Reactions on a specific message.

    Routes (nested under messages):
      GET    /api/v1/chat/messages/<message_pk>/reactions/                list
      POST   /api/v1/chat/messages/<message_pk>/reactions/                add {emoji}
      DELETE /api/v1/chat/messages/<message_pk>/reactions/<emoji>/        remove (own)
    """
    serializer_class = ReactionSerializer
    service_class = ChatService
    permission_classes = [IsAuthenticated]
    lookup_field = "emoji"           # delete keyed by emoji code, not row id
    lookup_value_regex = "[a-z0-9_+\\-]+"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return MessageReaction.objects.filter(message_id=self.kwargs["message_pk"])

    def get_object(self):
        return get_object_or_404(
            MessageReaction,
            message_id=self.kwargs["message_pk"],
            emoji=self.kwargs["emoji"],
            author_user=self.request.user,    # only own row deletable
        )
```

**Service methods** (auto-discovered by ServiceMethodMixin):
```python
# chat/services.py — add to ChatService
def create_messagereaction(self, *, emoji: str, **_) -> MessageReaction:
    message_id = self.kwargs["message_pk"]   # passed by mixin via viewset.kwargs
    if emoji not in CURATED_EMOJIS:
        raise ValidationError(f"unknown emoji: {emoji}")
    message = get_object_or_404(Message, id=message_id, channel__workspace=self.company)
    reaction, _ = MessageReaction.objects.get_or_create(
        message=message, emoji=emoji, author_user=self.current_user,
    )
    _broadcast_reaction(message.channel_id, message.id, emoji, self.current_user, added=True)
    return reaction


def delete_messagereaction(self, instance: MessageReaction) -> None:
    _broadcast_reaction(
        instance.message.channel_id, instance.message_id, instance.emoji,
        instance.author_user, added=False,
    )
    instance.delete()
```

**Router registration** — nested under MessageViewSet using `drf-nested-routers`:
```python
# chat/api/v1/urls.py
from rest_framework_nested.routers import NestedDefaultRouter

router = DefaultRouter()
router.register(r"messages", MessageViewSet, basename="message")
messages_router = NestedDefaultRouter(router, r"messages", lookup="message")
messages_router.register(r"reactions", ReactionViewSet, basename="message-reactions")
```

If `drf-nested-routers` isn't already a dep, alternative: flat route
`/api/v1/chat/messages/<id>/reactions/` wired manually via `path()` + `as_view({...})`.

**Serializer:** `MessageSerializer` gains `reactions: [{emoji, count, by_me}]`
aggregated via subquery — NO `by_donna` field (agents don't react).

**WS:** `chat.reaction.added` / `chat.reaction.removed` on `channel_group`.

### P7.2 Frontend — picker shared between reactions + inline insertion

**Emoji set sync:** ship parallel TS const at `web/src/lib/emojis.ts` mirroring
`chat/emojis.py`. Build script `scripts/sync_emojis.py` regenerates the TS
file from the Python dict (idempotent; run on emoji-set change).

**Picker:** `web/src/components/Channel/EmojiPicker.tsx`
- Single component, two consumers (reactions + composer).
- Static list from `lib/emojis.ts`.
- Search by code + keywords. Group by `people / objects / symbols / nature / ...`.
- Recent picks in localStorage (separate buckets for reactions vs inline).
- Prop `onPick: (emoji: EmojiEntry) => void` so consumer decides what to do.

**Reaction bar:** `web/src/components/Channel/ReactionBar.tsx`
- Rendered under each message.
- Group by emoji code; render unicode + count; highlight if `by_me`.
- Click existing reaction → toggle own (POST or DELETE).
- "+" button at end → opens EmojiPicker with `onPick = (e) => POST reaction`.

**Inline insertion in Composer:** `web/src/components/Channel/Composer.tsx`
- Emoji button next to send button → opens EmojiPicker.
- `onPick = (e) => insertAtCursor(e.unicode)` writes character into textarea.
- Also support `:code:` autocomplete: type `:thum` → dropdown shows matching
  codes; Tab/Enter inserts unicode char.

**Message.tsx integration:** hover reveals "Reply" + "React" + "Add reaction"
buttons. "React" opens EmojiPicker.

**WS handler:** on `chat.reaction.added/removed`, update message's reactions
array in state.

### P7.3 Verification

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test donna.chat.tests.test_reactions -v 2"
```

Smoke:
- React 👍 to a teammate's message → reaction bar shows "👍 1 (you)".
- Teammate reacts same emoji → "👍 2".
- Open Composer emoji picker → click 🎉 → emoji char appears in body at cursor.
- Type `:fire` in composer → dropdown shows 🔥 → Tab inserts `🔥`.

**Out of scope (confirmed):** agents do NOT react. No `AddReactionTool`. No
agent-author field on MessageReaction. Donna's "acknowledge / celebrate"
expression happens through normal assistant message text, not via reaction.

---

## Critical files (summary)

### New (backend)

| File | Phase | Purpose |
|---|---|---|
| `chat/migrations/0005_channelpin.py` | P2 | ChannelPin model |
| `chat/migrations/0006_message_threading_polish.py` | P1 | Verify Message.parent indexes |
| `chat/migrations/0007_message_mentions.py` | P6 | mentions M2M + mention_flags |
| `chat/migrations/0008_messagereaction.py` | P7 | MessageReaction model |
| `workspaces/migrations/000X_workspaceinvitation.py` | P5 | WorkspaceInvitation model |
| `users/migrations/000X_user_handle.py` | P6 | User.handle field + backfill |
| `chat/permissions.py` | P4 | `can_manage_channel_members` |
| `chat/mentions.py` | P6 | mention parser (chat infra, NOT under agents/) |
| `chat/emojis.py` | P7 | CURATED_EMOJIS dict (NOT under agents/ — chat infra) |
| `scripts/sync_emojis.py` | P7 | Regenerate `web/src/lib/emojis.ts` from Python dict |
| `workspaces/templates/workspaces/emails/invitation.{html,txt}` | P5 | Email templates |
| `chat/tests/test_dm.py` | P0 | DM get-or-create tests |
| `chat/tests/test_pins.py` | P2 | Pin tests |
| `chat/tests/test_invite_channel.py` | P4 | Channel member add/remove tests |
| `chat/tests/test_mentions.py` | P6 | Parser + fanout tests |
| `chat/tests/test_reactions.py` | P7 | User + agent reaction tests |
| `workspaces/tests/test_invitation.py` | P5 | Invite + accept tests |

### New (frontend)

| File | Phase |
|---|---|
| `web/src/components/Channel/StartDMDialog.tsx` | P0 |
| `web/src/components/Channel/ThreadPanel.tsx` | P1 |
| `web/src/components/Channel/DocumentsRail.tsx` | P3 |
| `web/src/components/Channel/InviteToChannelDialog.tsx` | P4 |
| `web/src/components/Shell/InviteToWorkspaceDialog.tsx` | P5 |
| `web/src/views/AcceptInvitation.tsx` | P5 |
| `web/src/components/Channel/EmojiPicker.tsx` | P7 |
| `web/src/components/Channel/ReactionBar.tsx` | P7 |
| `web/src/state/documents.ts` | P3 |

### Edited (backend)

| File | Phase | Change |
|---|---|---|
| `chat/models.py` | P2, P6, P7 | ChannelPin, Message.mentions+flags, MessageReaction |
| `chat/services.py` | P0, P6 | get_or_create_dm, create_message + mention fanout |
| `chat/api/v1/views.py` | P0, P2, P4, P7 | DM view, pin action, member actions, reaction view |
| `chat/api/v1/serializers.py` | P1, P2, P7 | reply_count, is_pinned, reactions aggregation |
| `chat/api/v1/urls.py` | P0, P4, P7 | DM, member, reaction routes |
| `chat/agents/tools/factory.py` | — | (no change in P7 — agents don't react) |
| `users/models.py` | P6 | handle field |
| `workspaces/models.py` | P5 | WorkspaceInvitation model |
| `workspaces/services.py` | P5 | create/verify/accept invitation |
| `workspaces/api/v1/views.py` + `urls.py` | P5 | invitation views |
| `donna/settings.py` | P5 | SMTP backend + EMAIL_* env |
| `donna/settings.py` | P5 | add `/api/v1/workspaces/invitations/` to IGNORED_PATHS |
| `donna/.env.example` | P5 | EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL, FRONTEND_BASE_URL |

### Edited (frontend)

| File | Phase | Change |
|---|---|---|
| `web/src/api/chat.ts` | P0, P2, P4, P7 | startDM, pin, addMember, reactions |
| `web/src/api/workspaces.ts` | P5 | invitation CRUD |
| `web/src/state/channels.ts` | P0, P2 | DM list, is_pinned |
| `web/src/state/messages.ts` | P1, P7 | threads, reactions |
| `web/src/components/Shell/Sidebar.tsx` | P0, P2 | Pinned section + DM section |
| `web/src/components/Channel/Composer.tsx` | P1, P6 | parent reply send + mention autocomplete |
| `web/src/components/Channel/Message.tsx` | P1, P6, P7 | thread chip + mention chips + reaction bar |
| `web/src/components/Channel/ChannelHeader.tsx` | P4 | Members button |
| `web/src/App.tsx` | P5 | AcceptInvitation route |
| `web/src/views/Channel.tsx` | P3 | mount DocumentsRail |
| `web/src/lib/ws.ts` | P0-P7 | route new WS events to state slices |

### Reused (no edit)

- `Channel.Kind.DIRECT`, `Channel.metadata` JSONField
- `Message.parent` FK
- `ChannelMembership` (P4 adds member via existing model)
- `WorkspaceMembership` (P5 invitations create rows)
- `Notification` model (P6 fans out via existing service)
- `ChannelDocumentsView` (P3)
- WS `channel_group`, `channel_typing_group` (P1, P6, P7)

---

## Migration order

1. `workspaces/000X_workspaceinvitation` (P5)
2. `users/000X_user_handle` (P6)
3. `chat/0005_channelpin` (P2)
4. `chat/0006_message_threading_polish` (P1) — index on `Message.parent` if missing
5. `chat/0007_message_mentions` (P6)
6. `chat/0008_messagereaction` (P7)

Run all in dev:
```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python manage.py makemigrations && uv run python manage.py migrate"
```

---

## Verification

### Per-phase tests

```bash
docker exec donna-server bash -lc "cd /opt/donna && DATABASE_HOST=donna-database \
   uv run python -m django test \
     donna.chat.tests.test_dm \
     donna.chat.tests.test_pins \
     donna.chat.tests.test_invite_channel \
     donna.chat.tests.test_mentions \
     donna.chat.tests.test_reactions \
     donna.workspaces.tests.test_invitation \
     -v 2"
```

### End-to-end smoke (after all 8 ship)

1. Create workspace; invite teammate via email. Teammate receives Gmail → clicks accept link → membership created.
2. Teammate starts DM with you. Both can chat.
3. Pin the DM. Sidebar shows it in Pinned section.
4. In a channel, send "hey @donna draft a status update". Donna agent responds, DocumentsRail shows draft live updates.
5. React 👍 to Donna's message. Open Composer emoji picker, insert 🎉 inline into the next reply (agents do NOT react).
6. Reply to a message in thread; reply count badge updates; ThreadPanel opens.
7. Send "@everyone team standup at 3" — all channel members get mention notification.
8. Add new teammate to channel via "Members" → "Invite". They appear in member list + their Sidebar shows the channel.

### Cleanup

```bash
bash server/scripts/cleanup_test_residue.sh
```

---

## Risks + open polish

1. **Gmail SMTP daily cap** — 500/day free or 2000/day Workspace. Beyond that → migrate to SES/SendGrid. Document in P5 README.
2. **Mention parser handle collisions** — backfill `User.handle = email_prefix` needs dedup. Append `-2`, `-3` on collision.
3. **Reaction count drift under high contention** — DB-level aggregation in serializer; if N×M renders slow, denormalize to `Message.reactions_summary` JSONField updated via signal.
4. **Thread depth** — current schema allows infinite nesting (`Message.parent` is self-FK). UI should hard-cap at 1 level (no replies-to-replies) to keep UX simple. Validate in serializer.
5. **DM scaling** — if a user joins 50 DMs, `Sidebar` rendering all is heavy. Add pagination + "Show more" pattern.
6. **Curated emoji list as source of truth** — backend list ships as Python dict. Frontend needs parallel TS const. Either: (a) generate TS from Python via build script, OR (b) ship `/api/v1/chat/emojis/` endpoint frontend fetches once. (b) is lazier but cleaner.
7. **Notification UX** — mention notifications stack in NotificationBell. Need badge per channel in Sidebar showing unread mention count. Existing `ChannelReadState` doesn't track mentions distinctly; add `unread_mention_count` denormalized field or query-time count.
8. **Donna agent reaction tool — over-use risk** — system prompt should explicitly say "react sparingly; only when natural". Add to `prompts.py` system prompt.

---

## Open questions

1. **Public Donna handle resolution.** `@donna` always = the channel's bound agent. Multi-agent later → `@<agent-name>`. For v1, single name fine.
2. **DM with self.** Allowed (private notes channel) or rejected (current plan rejects)? Common in Slack. Recommend: rejected for v1, add later as `Channel.Kind.SELF` if asked.
3. **DM groups (3+ people).** Plan only supports 2-person DMs. Slack has multi-person DMs. Defer to v2 — model can extend trivially by dropping the sorted-pair uniqueness.
4. **Mention notifications for self-mentions.** Should `@alice` notify alice if alice is the author? Recommend: no (Slack convention).
5. **Reaction undo TTL.** Permanent or 1h grace? Plan allows permanent toggle (no TTL). Slack-style. Keep.
6. **Threading WS routing.** Send to `channel_group` always OR separate `thread_group` for noise reduction? Recommend: same `channel_group`, frontend filters by `parent_id`.

---
