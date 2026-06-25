"""Workspace invitation tests — create, sign, accept, revoke, expire."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from donna.workspaces.models import (
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from donna.workspaces.services import WorkspaceInvitationService


User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitationCreateTests(TestCase):
    def _setup(self):
        owner = User.objects.create_user(email="o@x", password="x")
        ws = Workspace.objects.create(name="T", slug="iv1", created_by=owner, modified_by=owner)
        WorkspaceMembership.objects.create(
            workspace=ws, user=owner, role=WorkspaceMembership.Role.OWNER,
        )
        return owner, ws

    def test_create_sends_email_and_returns_pending(self):
        owner, ws = self._setup()
        svc = WorkspaceInvitationService(current_user=owner, company=ws)
        mail.outbox = []

        invite = svc.create({"email": "newbie@example.com", "role": "member"})

        self.assertEqual(invite.status, WorkspaceInvitation.Status.PENDING)
        self.assertEqual(invite.email, "newbie@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("invited", mail.outbox[0].subject.lower())
        self.assertIn("newbie@example.com", mail.outbox[0].to)

    def test_create_revokes_existing_pending_for_same_email(self):
        owner, ws = self._setup()
        svc = WorkspaceInvitationService(current_user=owner, company=ws)

        first = svc.create({"email": "dup@example.com"})
        second = svc.create({"email": "dup@example.com"})

        first.refresh_from_db()
        self.assertEqual(first.status, WorkspaceInvitation.Status.REVOKED)
        self.assertEqual(second.status, WorkspaceInvitation.Status.PENDING)

    def test_create_rejects_existing_member(self):
        owner, ws = self._setup()
        existing = User.objects.create_user(email="member@x", password="x")
        WorkspaceMembership.objects.create(workspace=ws, user=existing)
        svc = WorkspaceInvitationService(current_user=owner, company=ws)

        with self.assertRaises(ValidationError):
            svc.create({"email": "member@x"})

    def test_create_rejects_owner_role(self):
        owner, ws = self._setup()
        svc = WorkspaceInvitationService(current_user=owner, company=ws)

        with self.assertRaises(ValidationError):
            svc.create({"email": "new@x", "role": WorkspaceMembership.Role.OWNER})


class InvitationTokenTests(TestCase):
    def _setup_invite(self):
        owner = User.objects.create_user(email="o@x", password="x")
        ws = Workspace.objects.create(name="T", slug="iv2", created_by=owner, modified_by=owner)
        WorkspaceMembership.objects.create(
            workspace=ws, user=owner, role=WorkspaceMembership.Role.OWNER,
        )
        invite = WorkspaceInvitation.objects.create(
            workspace=ws, invited_by=owner,
            email="who@x", role=WorkspaceMembership.Role.MEMBER,
            expires_at=timezone.now() + timedelta(days=1),
        )
        return owner, ws, invite

    def test_verify_token_returns_invite(self):
        _, _, invite = self._setup_invite()
        token = WorkspaceInvitationService._sign_token(invite)

        out = WorkspaceInvitationService.verify_token(token)

        self.assertEqual(out.id, invite.id)

    def test_verify_token_rejects_bad_signature(self):
        with self.assertRaises(ValidationError):
            WorkspaceInvitationService.verify_token("bad.token.here")

    def test_verify_token_rejects_revoked(self):
        _, _, invite = self._setup_invite()
        token = WorkspaceInvitationService._sign_token(invite)
        invite.status = WorkspaceInvitation.Status.REVOKED
        invite.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            WorkspaceInvitationService.verify_token(token)

    def test_verify_token_rejects_expired_and_marks_status(self):
        _, _, invite = self._setup_invite()
        token = WorkspaceInvitationService._sign_token(invite)
        invite.expires_at = timezone.now() - timedelta(hours=1)
        invite.save(update_fields=["expires_at"])

        with self.assertRaises(ValidationError):
            WorkspaceInvitationService.verify_token(token)

        invite.refresh_from_db()
        self.assertEqual(invite.status, WorkspaceInvitation.Status.EXPIRED)


class InvitationAcceptTests(TestCase):
    def _setup_pending(self):
        owner = User.objects.create_user(email="o@x", password="x")
        ws = Workspace.objects.create(name="T", slug="iv3", created_by=owner, modified_by=owner)
        WorkspaceMembership.objects.create(
            workspace=ws, user=owner, role=WorkspaceMembership.Role.OWNER,
        )
        invite = WorkspaceInvitation.objects.create(
            workspace=ws, invited_by=owner,
            email="newbie@x", role=WorkspaceMembership.Role.MEMBER,
            expires_at=timezone.now() + timedelta(days=1),
        )
        token = WorkspaceInvitationService._sign_token(invite)
        return ws, invite, token

    def test_accept_creates_membership(self):
        ws, invite, token = self._setup_pending()
        acceptor = User.objects.create_user(email="newbie@x", password="x")
        svc = WorkspaceInvitationService(current_user=acceptor, company=None)

        membership = svc.accept(token=token, accepting_user=acceptor)

        self.assertEqual(membership.workspace_id, ws.id)
        self.assertEqual(membership.user_id, acceptor.id)
        self.assertEqual(membership.role, WorkspaceMembership.Role.MEMBER)
        invite.refresh_from_db()
        self.assertEqual(invite.status, WorkspaceInvitation.Status.ACCEPTED)
        self.assertEqual(invite.accepted_by_id, acceptor.id)

    def test_accept_rejects_email_mismatch(self):
        _, _, token = self._setup_pending()
        stranger = User.objects.create_user(email="stranger@x", password="x")
        svc = WorkspaceInvitationService(current_user=stranger, company=None)

        with self.assertRaises(ValidationError):
            svc.accept(token=token, accepting_user=stranger)

    def test_double_accept_rejected(self):
        _, _, token = self._setup_pending()
        acceptor = User.objects.create_user(email="newbie@x", password="x")
        svc = WorkspaceInvitationService(current_user=acceptor, company=None)
        svc.accept(token=token, accepting_user=acceptor)

        with self.assertRaises(ValidationError):
            svc.accept(token=token, accepting_user=acceptor)
