"""
Workspace + membership viewset coverage — list scoping, role change,
last-owner refusal, kick semantics, ownership transfer, and the
``InvitationService.revoke`` service method (no REST endpoint yet).
"""
from __future__ import annotations

from django.test import TestCase

from donna.audit.models import AuditLog
from donna.core.tests.helpers import api_client, envelope
from donna.users.tests.factories import make_user
from donna.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from donna.workspaces.services import (
    InvitationService,
    WorkspaceMembershipService,
)
from donna.workspaces.tests.factories import make_workspace


# ── Workspace CRUD ──────────────────────────────────────────────────────────
class WorkspaceCRUDTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@wsc.test")
        cls.bob = make_user(email="bob@wsc.test")
        cls.outsider = make_user(email="outsider@wsc.test")
        cls.workspace = make_workspace(
            name="WSC", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )
        cls.other_workspace = make_workspace(name="WSC-Other", owner=cls.outsider)

    def test_list_returns_only_my_workspaces(self):
        c = api_client(user=self.alice)
        r = c.get("/api/v1/workspaces/")
        self.assertEqual(r.status_code, 200)
        ids = {w["id"] for w in envelope(r)}
        self.assertIn(str(self.workspace.id), ids)
        self.assertNotIn(str(self.other_workspace.id), ids)

    def test_list_includes_my_role(self):
        c = api_client(user=self.alice)
        r = c.get("/api/v1/workspaces/")
        rows = {w["id"]: w for w in envelope(r)}
        self.assertEqual(rows[str(self.workspace.id)]["my_role"], "owner")

    def test_retrieve_as_member_returns_200(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.get(f"/api/v1/workspaces/{self.workspace.id}/")
        self.assertEqual(r.status_code, 200)

    def test_create_workspace_seeds_owner_membership(self):
        c = api_client(user=self.bob)
        r = c.post("/api/v1/workspaces/", {"name": "Bob's WS"}, format="json")
        self.assertEqual(r.status_code, 201)
        ws_id = envelope(r)["id"]
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace_id=ws_id, user=self.bob,
                role=WorkspaceMembership.Role.OWNER,
            ).exists()
        )

    def test_create_generates_unique_slug(self):
        c = api_client(user=self.bob)
        r1 = c.post("/api/v1/workspaces/", {"name": "Dup"}, format="json")
        r2 = c.post("/api/v1/workspaces/", {"name": "Dup"}, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertNotEqual(envelope(r1)["slug"], envelope(r2)["slug"])

    def test_patch_as_admin_updates(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/workspaces/{self.workspace.id}/",
            {"name": "Renamed"}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.name, "Renamed")

    def test_patch_as_plain_member_forbidden(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/workspaces/{self.workspace.id}/",
            {"name": "Hijacked"}, format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_delete_as_owner(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(f"/api/v1/workspaces/{self.workspace.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(
            Workspace.objects.filter(id=self.workspace.id).exists()
        )

    def test_delete_as_plain_member_forbidden(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(f"/api/v1/workspaces/{self.workspace.id}/")
        self.assertEqual(r.status_code, 403)


# ── Membership viewset ──────────────────────────────────────────────────────
class WorkspaceMembershipViewSetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@m.test")
        cls.bob = make_user(email="bob@m.test")
        cls.carol = make_user(email="carol@m.test")  # external — no membership
        cls.dave = make_user(email="dave@m.test")
        cls.workspace = make_workspace(
            name="MemViewWS", owner=cls.alice,
            members=[
                (cls.bob, WorkspaceMembership.Role.MEMBER),
                (cls.dave, WorkspaceMembership.Role.ADMIN),
            ],
        )

    def test_list_returns_workspace_members(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/members/")
        self.assertEqual(r.status_code, 200)
        emails = {m["user"]["email"] for m in envelope(r)}
        self.assertEqual(
            emails,
            {"alice@m.test", "bob@m.test", "dave@m.test"},
        )

    def test_retrieve_by_user_id(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get(f"/api/v1/members/{self.bob.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["role"], "member")

    def test_admin_adds_existing_user(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/members/",
            {"user_id": str(self.carol.id), "role": "member"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace, user=self.carol
            ).exists()
        )

    def test_plain_member_cannot_add(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.post(
            "/api/v1/members/",
            {"user_id": str(self.carol.id)},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_duplicate_membership_rejected(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/members/",
            {"user_id": str(self.bob.id), "role": "member"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_cannot_invite_directly_as_owner(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/members/",
            {"user_id": str(self.carol.id), "role": "owner"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_role_change_records_audit(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        before = AuditLog.objects.filter(
            action="workspace.member.role_changed"
        ).count()
        r = c.patch(
            f"/api/v1/members/{self.bob.id}/",
            {"role": "admin"}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        after = AuditLog.objects.filter(
            action="workspace.member.role_changed"
        ).count()
        self.assertEqual(after, before + 1)

    def test_ownership_transfer_demotes_old_owner(self):
        # Promote dave to OWNER — alice must be demoted to ADMIN atomically.
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/members/{self.dave.id}/",
            {"role": "owner"}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        alice_m = WorkspaceMembership.objects.get(
            workspace=self.workspace, user=self.alice
        )
        self.assertEqual(alice_m.role, WorkspaceMembership.Role.ADMIN)
        dave_m = WorkspaceMembership.objects.get(
            workspace=self.workspace, user=self.dave
        )
        self.assertEqual(dave_m.role, WorkspaceMembership.Role.OWNER)

    def test_last_owner_cannot_be_demoted(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            f"/api/v1/members/{self.alice.id}/",
            {"role": "admin"}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_last_owner_cannot_be_deleted(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(f"/api/v1/members/{self.alice.id}/")
        self.assertEqual(r.status_code, 400)
        # Still a member.
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace, user=self.alice
            ).exists()
        )

    def test_admin_kick_records_audit(self):
        before = AuditLog.objects.filter(
            action="workspace.member.removed"
        ).count()
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete(f"/api/v1/members/{self.bob.id}/")
        self.assertEqual(r.status_code, 204)
        after = AuditLog.objects.filter(
            action="workspace.member.removed"
        ).count()
        self.assertEqual(after, before + 1)

    def test_self_leave(self):
        c = api_client(user=self.bob, workspace=self.workspace)
        r = c.delete(f"/api/v1/members/{self.bob.id}/")
        self.assertEqual(r.status_code, 204)


# ── InvitationService.revoke (no REST endpoint yet) ─────────────────────────
class InvitationRevokeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@rev.test")
        cls.workspace = make_workspace(name="RevWS", owner=cls.alice)
        cls.invitation = WorkspaceInvitation.objects.create(
            workspace=cls.workspace, invited_by=cls.alice,
            email="someone@example.com",
        )

    def test_revoke_sets_status_and_audits(self):
        before = AuditLog.objects.filter(
            action="workspace.invitation.revoked"
        ).count()
        result = InvitationService.revoke(
            invitation=self.invitation, by_user=self.alice
        )
        self.assertEqual(result.status, WorkspaceInvitation.Status.REVOKED)
        self.assertEqual(
            AuditLog.objects.filter(
                action="workspace.invitation.revoked"
            ).count(),
            before + 1,
        )

    def test_revoke_already_accepted_raises(self):
        from rest_framework.exceptions import ValidationError

        self.invitation.status = WorkspaceInvitation.Status.ACCEPTED
        self.invitation.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            InvitationService.revoke(
                invitation=self.invitation, by_user=self.alice
            )

    def test_revoke_blocks_subsequent_accept(self):
        from rest_framework.exceptions import ValidationError

        InvitationService.revoke(
            invitation=self.invitation, by_user=self.alice
        )
        recipient = make_user(email="recipient@rev.test")
        with self.assertRaises(ValidationError):
            InvitationService.accept(
                token=self.invitation.token, user=recipient,
            )
