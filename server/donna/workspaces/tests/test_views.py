"""
Phase 2a integration — workspace invitation REST surface.

  POST /api/v1/invitations/                (admin sends; needs X-Workspace-Id)
  GET  /api/v1/invitations/{token}/        (anonymous preview)
  POST /api/v1/invitations/{token}/accept/ (signed-in user accepts)
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from donna.audit.models import AuditLog
from donna.core.tests.helpers import api_client, envelope
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceInvitation, WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


class InvitationCreateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@inv.test")  # owner
        cls.bob = make_user(email="bob@inv.test")      # plain member
        cls.workspace = make_workspace(
            name="Inv-WS", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )

    def test_admin_can_create_email_invitation(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/invitations/",
            {"email": "guest@example.com", "role": "member"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        body = envelope(r)
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["email"], "guest@example.com")
        self.assertTrue(body["token"])

    def test_admin_can_create_link_invitation(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post("/api/v1/invitations/", {}, format="json")
        self.assertEqual(r.status_code, 201)
        body = envelope(r)
        self.assertEqual(body["email"], "")
        self.assertTrue(body["token"])

    def test_non_admin_member_cannot_invite(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            "/api/v1/invitations/", {"email": "x@example.com"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_owner_role_rejected(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/invitations/", {"role": "owner"}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_missing_workspace_header_returns_400(self):
        # Even though the prefix is in IGNORED_PATHS, the create view
        # requires X-Workspace-Id itself.
        c = api_client(user=self.alice)  # no workspace header
        r = c.post(
            "/api/v1/invitations/", {"email": "x@example.com"}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_audit_row_recorded_on_create(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        before = AuditLog.objects.filter(
            action="workspace.invitation.created"
        ).count()
        r = c.post(
            "/api/v1/invitations/", {"email": "audit@example.com"}, format="json",
        )
        self.assertEqual(r.status_code, 201)
        after = AuditLog.objects.filter(
            action="workspace.invitation.created"
        ).count()
        self.assertEqual(after, before + 1)


class InvitationPreviewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@prev.test")
        cls.workspace = make_workspace(name="Preview-WS", owner=cls.alice)
        cls.invitation = WorkspaceInvitation.objects.create(
            workspace=cls.workspace, invited_by=cls.alice,
            email="prev@example.com",
        )

    def test_anonymous_preview_returns_workspace_metadata(self):
        anon = api_client()
        r = anon.get(f"/api/v1/invitations/{self.invitation.token}/")
        self.assertEqual(r.status_code, 200)
        body = envelope(r)
        self.assertEqual(body["workspace_name"], "Preview-WS")
        self.assertEqual(body["role"], "member")
        # Token is NOT echoed back — caller already has it.
        self.assertNotIn("token", body)

    def test_bogus_token_returns_404(self):
        anon = api_client()
        r = anon.get("/api/v1/invitations/not-a-real-token-xxx/")
        self.assertEqual(r.status_code, 404)

    def test_revoked_invitation_returns_400(self):
        from donna.workspaces.services import InvitationService

        InvitationService.revoke(invitation=self.invitation, by_user=self.alice)
        anon = api_client()
        r = anon.get(f"/api/v1/invitations/{self.invitation.token}/")
        self.assertEqual(r.status_code, 400)

    def test_expired_invitation_returns_400(self):
        # Backdate
        self.invitation.expires_at = timezone.now() - timedelta(hours=1)
        self.invitation.save(update_fields=["expires_at"])
        anon = api_client()
        r = anon.get(f"/api/v1/invitations/{self.invitation.token}/")
        self.assertEqual(r.status_code, 400)
        self.invitation.refresh_from_db()
        # And the row's status is bookkept to EXPIRED.
        self.assertEqual(self.invitation.status, WorkspaceInvitation.Status.EXPIRED)


class InvitationAcceptTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@acc.test")
        cls.eve = make_user(email="eve@acc.test")
        cls.workspace = make_workspace(name="Accept-WS", owner=cls.alice)
        cls.invitation = WorkspaceInvitation.objects.create(
            workspace=cls.workspace, invited_by=cls.alice,
            email="eve@acc.test", role=WorkspaceMembership.Role.MEMBER,
        )

    def test_signed_in_user_accepts_and_joins_workspace(self):
        c = api_client(user=self.eve)
        r = c.post(f"/api/v1/invitations/{self.invitation.token}/accept/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["role"], "member")
        # Membership row exists.
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace, user=self.eve
            ).exists()
        )

    def test_double_accept_returns_400(self):
        c = api_client(user=self.eve)
        first = c.post(f"/api/v1/invitations/{self.invitation.token}/accept/")
        self.assertEqual(first.status_code, 200)
        second = c.post(f"/api/v1/invitations/{self.invitation.token}/accept/")
        self.assertEqual(second.status_code, 400)

    def test_anonymous_accept_returns_401(self):
        anon = api_client()
        r = anon.post(f"/api/v1/invitations/{self.invitation.token}/accept/")
        self.assertEqual(r.status_code, 401)

    def test_audit_row_recorded_on_accept(self):
        before = AuditLog.objects.filter(
            action="workspace.invitation.accepted"
        ).count()
        c = api_client(user=self.eve)
        c.post(f"/api/v1/invitations/{self.invitation.token}/accept/")
        after = AuditLog.objects.filter(
            action="workspace.invitation.accepted"
        ).count()
        self.assertEqual(after, before + 1)
