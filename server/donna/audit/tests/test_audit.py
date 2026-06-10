"""
AuditService tests — basic behavior + best-effort error swallowing.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from donna.audit.models import AuditLog
from donna.audit.services import AuditService
from donna.chat.services import ChannelService
from donna.chat.tests.factories import make_channel
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


class AuditServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@audit.test")
        cls.workspace = make_workspace(name="AuditWS", owner=cls.alice)

    def test_record_creates_row_with_target_metadata(self):
        before = AuditLog.objects.count()
        entry = AuditService.record(
            action="test.event",
            actor=self.alice,
            workspace=self.workspace,
            target=self.workspace,
            context={"why": "because"},
        )
        self.assertIsNotNone(entry)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        self.assertEqual(entry.action, "test.event")
        self.assertEqual(entry.actor_id, self.alice.id)
        self.assertEqual(entry.workspace_id, self.workspace.id)
        self.assertEqual(entry.target_type, "Workspace")
        self.assertEqual(entry.target_id, str(self.workspace.id))
        self.assertEqual(entry.context["why"], "because")

    def test_record_without_target_leaves_blank_target_fields(self):
        entry = AuditService.record(
            action="system.event",
            actor=self.alice,
        )
        self.assertEqual(entry.target_type, "")
        self.assertEqual(entry.target_id, "")

    def test_record_swallows_db_errors_returns_none(self):
        """A best-effort record must never fail the user-visible flow."""
        with patch(
            "donna.audit.services.AuditLog.objects.create",
            side_effect=RuntimeError("db boom"),
        ):
            result = AuditService.record(
                action="boom.event", actor=self.alice, workspace=self.workspace,
            )
        self.assertIsNone(result)


class AuditIntegrationTest(TestCase):
    """Verify the service emits an audit row at each documented call site."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@audit-int.test")
        cls.bob = make_user(email="bob@audit-int.test")
        cls.workspace = make_workspace(
            name="AuditIntWS", owner=cls.alice,
            members=[(cls.bob, WorkspaceMembership.Role.MEMBER)],
        )
        cls.channel = make_channel(
            workspace=cls.workspace, name="general", slug="general",
            admins=[cls.alice],
        )

    def test_chat_add_member_emits_channel_member_added(self):
        before = AuditLog.objects.filter(action="channel.member.added").count()
        ChannelService.add_member(
            channel=self.channel, user=self.bob, added_by=self.alice,
        )
        after = AuditLog.objects.filter(action="channel.member.added").count()
        self.assertEqual(after, before + 1)

    def test_chat_remove_member_emits_channel_member_removed(self):
        ChannelService.add_member(
            channel=self.channel, user=self.bob, added_by=self.alice,
        )
        before = AuditLog.objects.filter(action="channel.member.removed").count()
        ChannelService.remove_member(
            channel=self.channel, user=self.bob, removed_by=self.alice,
        )
        after = AuditLog.objects.filter(action="channel.member.removed").count()
        self.assertEqual(after, before + 1)

    def test_invitation_create_and_accept_emit_audit_rows(self):
        from donna.workspaces.services import InvitationService

        before_c = AuditLog.objects.filter(
            action="workspace.invitation.created"
        ).count()
        inv = InvitationService.create(
            workspace=self.workspace, invited_by=self.alice,
            email="newcomer@audit-int.test",
        )
        self.assertEqual(
            AuditLog.objects.filter(
                action="workspace.invitation.created"
            ).count(),
            before_c + 1,
        )

        newcomer = make_user(email="newcomer@audit-int.test")
        before_a = AuditLog.objects.filter(
            action="workspace.invitation.accepted"
        ).count()
        InvitationService.accept(token=inv.token, user=newcomer)
        self.assertEqual(
            AuditLog.objects.filter(
                action="workspace.invitation.accepted"
            ).count(),
            before_a + 1,
        )
