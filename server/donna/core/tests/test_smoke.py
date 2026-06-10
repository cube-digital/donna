"""
End-to-end smoke suite — one happy path per shipped endpoint.

Goals:
- Catch the dumb regressions: 500s, URL drift, schema mismatches.
- Run in seconds (single test method, sequential calls).
- Stay shallow: behavior depth lives in per-feature integration tests.

Covered surface (current as of Phase 0–2):
  Auth:        POST /api/auth/signup, /api/auth/signin
  Workspaces:  POST /api/v1/workspaces/
  Channels:    POST /api/v1/chat/channels/
               GET  /api/v1/chat/channels/
               PATCH /api/v1/chat/channels/{id}/
               GET  /api/v1/chat/channels/{id}/
  Members:     POST /api/v1/chat/channels/{id}/members/   (admin add)
               GET  /api/v1/chat/channels/{id}/members/
               DELETE /api/v1/chat/channels/{id}/members/{user_id}/
  Messages:    POST /api/v1/chat/channels/{id}/messages/
               GET  /api/v1/chat/channels/{id}/messages/
               PATCH /api/v1/chat/messages/{id}/
               DELETE /api/v1/chat/messages/{id}/
  Read state:  GET/POST /api/v1/chat/channels/{id}/read-state/
  DMs:         POST /api/v1/chat/dms/, /chat/dms/group/
  Invitations: POST /api/v1/invitations/
               GET  /api/v1/invitations/{token}/
               POST /api/v1/invitations/{token}/accept/
  SSE:         GET /api/v1/notifications/stream  (401 without auth)

Behavioral checks live in the per-feature integration suites; this one
exists to scream when something obvious breaks.
"""
from __future__ import annotations

from django.test import TestCase

from donna.chat.models import Channel
from donna.core.tests.helpers import api_client, envelope
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


class SmokeTest(TestCase):
    """One method per endpoint group. APIClient runs in-process — no live stack."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(email="owner@smoke.test")
        cls.peer = make_user(email="peer@smoke.test")
        cls.outsider = make_user(email="outsider@smoke.test")
        cls.workspace = make_workspace(
            name="Smoke", owner=cls.owner,
            members=[(cls.peer, WorkspaceMembership.Role.MEMBER)],
        )

    # ── Auth ────────────────────────────────────────────────────────────────
    def test_signup_signin(self):
        c = api_client()  # no auth
        r = c.post(
            "/api/auth/signup",
            {"email": "new@smoke.test", "password": "S3curePass!2026", "full_name": "New"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

        r = c.post(
            "/api/auth/signin",
            {"email": "new@smoke.test", "password": "S3curePass!2026"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", envelope(r))

    # ── Workspaces ──────────────────────────────────────────────────────────
    def test_workspace_create(self):
        c = api_client(user=self.owner)
        r = c.post("/api/v1/workspaces/", {"name": "Smoke-2"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    # ── Channels CRUD ───────────────────────────────────────────────────────
    def test_channel_crud(self):
        c = api_client(user=self.owner, workspace=self.workspace)

        # Create
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "general", "slug": "general", "visibility": "public"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        cid = envelope(r)["id"]

        # List
        r = c.get("/api/v1/chat/channels/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any(ch["id"] == cid for ch in envelope(r)))

        # Retrieve
        r = c.get(f"/api/v1/chat/channels/{cid}/")
        self.assertEqual(r.status_code, 200, r.content)

        # Patch (topic + settings flag)
        r = c.patch(
            f"/api/v1/chat/channels/{cid}/",
            {"topic": "chit-chat", "settings": {"allow_member_invites": True}},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = envelope(r)
        self.assertEqual(body["topic"], "chit-chat")
        self.assertTrue(body["settings"]["allow_member_invites"])

    # ── Membership endpoints ────────────────────────────────────────────────
    def test_channel_members(self):
        c = api_client(user=self.owner, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "members-room", "slug": "members-room", "visibility": "private"},
            format="json",
        )
        cid = envelope(r)["id"]

        # Admin adds peer
        r = c.post(
            f"/api/v1/chat/channels/{cid}/members/",
            {"user_id": str(self.peer.id)},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

        # List members
        r = c.get(f"/api/v1/chat/channels/{cid}/members/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(envelope(r)), 2)  # owner + peer

        # Peer leaves
        peer_client = api_client(user=self.peer, workspace=self.workspace)
        r = peer_client.delete(
            f"/api/v1/chat/channels/{cid}/members/{self.peer.id}/"
        )
        self.assertEqual(r.status_code, 204, r.content)

    # ── Messages + read state ───────────────────────────────────────────────
    def test_messages_and_read_state(self):
        c = api_client(user=self.owner, workspace=self.workspace)
        r = c.post(
            "/api/v1/chat/channels/",
            {"name": "msg-room", "slug": "msg-room"},
            format="json",
        )
        cid = envelope(r)["id"]

        # Send
        r = c.post(
            f"/api/v1/chat/channels/{cid}/messages/",
            {"body": "hello"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        mid = envelope(r)["id"]

        # List
        r = c.get(f"/api/v1/chat/channels/{cid}/messages/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(any(m["id"] == mid for m in envelope(r)))

        # Edit
        r = c.patch(
            f"/api/v1/chat/messages/{mid}/",
            {"body": "hello (edited)"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)

        # Read state GET (before any pointer set)
        r = c.get(f"/api/v1/chat/channels/{cid}/read-state/")
        self.assertEqual(r.status_code, 200, r.content)

        # Advance read pointer
        r = c.post(
            f"/api/v1/chat/channels/{cid}/read-state/",
            {"message_id": mid},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(envelope(r)["unread_count"], 0)

        # Delete
        r = c.delete(f"/api/v1/chat/messages/{mid}/")
        self.assertEqual(r.status_code, 204, r.content)

    # ── DMs ─────────────────────────────────────────────────────────────────
    def test_dms_open(self):
        c = api_client(user=self.owner, workspace=self.workspace)

        # 1:1 DM
        r = c.post(
            "/api/v1/chat/dms/",
            {"peer_user_id": str(self.peer.id)},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(envelope(r)["kind"], Channel.Kind.DIRECT)

        # Group DM with three users
        third = make_user(email="third@smoke.test")
        WorkspaceMembership.objects.create(
            workspace=self.workspace, user=third,
            role=WorkspaceMembership.Role.MEMBER,
        )
        r = c.post(
            "/api/v1/chat/dms/group/",
            {"peer_user_ids": [str(self.peer.id), str(third.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)

    # ── Invitations ─────────────────────────────────────────────────────────
    def test_invitation_full_lifecycle(self):
        c_owner = api_client(user=self.owner, workspace=self.workspace)
        r = c_owner.post(
            "/api/v1/invitations/",
            {"email": "guest@smoke.test", "role": "member"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        token = envelope(r)["token"]

        # Anonymous preview
        anon = api_client()
        r = anon.get(f"/api/v1/invitations/{token}/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(envelope(r)["workspace_name"], "Smoke")

        # Accept (requires auth) — outsider takes the invite
        c_outsider = api_client(user=self.outsider)
        r = c_outsider.post(f"/api/v1/invitations/{token}/accept/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(envelope(r)["role"], "member")

        # Re-accept: 400 (invitation now consumed)
        r = c_outsider.post(f"/api/v1/invitations/{token}/accept/")
        self.assertEqual(r.status_code, 400, r.content)

    # ── SSE auth (transport-only; delivery is in test_phase0_sse) ───────────
    def test_sse_requires_bearer(self):
        anon = api_client()
        r = anon.get("/api/v1/notifications/stream")
        # StreamingHttpResponse so no .content — only assert status.
        self.assertEqual(r.status_code, 401)

    # ── Health ──────────────────────────────────────────────────────────────
    def test_health_is_public(self):
        """``GET /api/health/`` returns 200 with no auth + no workspace header.

        Used by k8s liveness/readiness probes and uptime monitors —
        must never depend on tenant context.
        """
        anon = api_client()
        r = anon.get("/api/health/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
