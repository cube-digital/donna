"""
Phase 0 integration — SSE auth + delivery.

The endpoint is a plain async Django view (not DRF), so Django's
``AuthenticationMiddleware`` doesn't run DRF auth and ``request.user``
is anonymous unless the view decodes the bearer header itself
(:func:`donna.notifications.api.v1.views._authenticate_sse_request`).

These tests exercise:
- 401 with no/bad bearer header.
- 200 with a valid bearer header.
- The bearer path's :func:`resolve_jwt_user` is identical to the WS
  subprotocol auth path.

End-to-end SSE delivery (Redis pubsub → stream) is covered by the
live curl/Django-shell probe documented in
``server/plans/10-realtime-layer.md`` §Verification — too slow + Redis-
dependent for the unit suite.
"""
from __future__ import annotations

from django.test import TestCase, TransactionTestCase

from donna.core.tests.helpers import api_client, envelope, jwt_for
from donna.notifications.models import Notification, NotificationScope
from donna.users.tests.factories import make_user
from donna.workspaces.models import WorkspaceMembership
from donna.workspaces.tests.factories import make_workspace


class SSERejectionTest(TestCase):
    """Auth-rejection paths — JWT validation fails *before* any DB lookup,
    so a plain TestCase (transactional) is fine and faster."""

    def test_no_authorization_header_returns_401(self):
        anon = api_client()
        r = anon.get("/api/v1/notifications/stream")
        self.assertEqual(r.status_code, 401)

    def test_malformed_bearer_returns_401(self):
        client = api_client()
        client.credentials(HTTP_AUTHORIZATION="Bearer not.a.real.jwt")
        r = client.get("/api/v1/notifications/stream")
        self.assertEqual(r.status_code, 401)

    def test_non_bearer_scheme_returns_401(self):
        client = api_client()
        client.credentials(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")
        r = client.get("/api/v1/notifications/stream")
        self.assertEqual(r.status_code, 401)


class SSEValidAuthTest(TransactionTestCase):
    """Paths that hit the DB through ``database_sync_to_async``.

    The async user lookup runs in a separate thread with its own
    connection; a transactional ``TestCase`` would have its writes
    invisible to that connection (rollback semantics). ``TransactionTestCase``
    commits between tests so the user the JWT points at actually exists
    in the DB the async thread queries.
    """

    def setUp(self):
        self.alice = make_user(email="alice@sse.test")

    def test_valid_jwt_authenticates(self):
        client = api_client()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_for(self.alice)}")
        r = client.get("/api/v1/notifications/stream")
        # 200 + StreamingHttpResponse; we only validate the headline status
        # to avoid blocking on the (long-lived) generator.
        self.assertEqual(r.status_code, 200)
        # Close so the SSE generator + Redis subscriber unwind cleanly.
        r.close()

    def test_resolve_jwt_user_returns_anonymous_for_bad_token(self):
        """Direct test of the helper reused by SSE + WS transports."""
        import asyncio

        from django.contrib.auth.models import AnonymousUser
        from donna.chat.auth import resolve_jwt_user

        u = asyncio.run(resolve_jwt_user("not.a.real.jwt"))
        self.assertIsInstance(u, AnonymousUser)

    def test_resolve_jwt_user_returns_user_for_valid_token(self):
        import asyncio

        from donna.chat.auth import resolve_jwt_user

        token = jwt_for(self.alice)
        u = asyncio.run(resolve_jwt_user(token))
        self.assertEqual(u.id, self.alice.id)


# ── Notifications REST viewset ──────────────────────────────────────────────
class NotificationsListRetrieveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@notif.test")
        cls.bob = make_user(email="bob@notif.test")
        cls.workspace = make_workspace(name="NotifWS", owner=cls.alice)
        # Seed: 3 for alice, 1 for bob — confirms user scoping.
        cls.n_alice_1 = Notification.objects.create(
            user=cls.alice, title="a1", message="...", scope=NotificationScope.USER,
        )
        cls.n_alice_2 = Notification.objects.create(
            user=cls.alice, title="a2", message="...", scope=NotificationScope.USER,
        )
        cls.n_alice_seen = Notification.objects.create(
            user=cls.alice, title="a3", message="...", seen=True,
        )
        cls.n_bob = Notification.objects.create(
            user=cls.bob, title="b1", message="...",
        )

    def test_list_scoped_to_caller(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/notifications/")
        self.assertEqual(r.status_code, 200)
        ids = {n["id"] for n in envelope(r)}
        self.assertIn(str(self.n_alice_1.id), ids)
        self.assertIn(str(self.n_alice_2.id), ids)
        self.assertNotIn(str(self.n_bob.id), ids)

    def test_list_ordered_newest_first(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/notifications/")
        results = envelope(r)
        # Newest = the latest-created. setUpTestData creates in order; the
        # final row (seen=True) was created last.
        self.assertEqual(results[0]["id"], str(self.n_alice_seen.id))

    def test_retrieve_returns_notification(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get(f"/api/v1/notifications/{self.n_alice_1.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["title"], "a1")

    def test_retrieve_other_users_notification_404(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get(f"/api/v1/notifications/{self.n_bob.id}/")
        self.assertEqual(r.status_code, 404)

    def test_unauthenticated_list_401(self):
        c = api_client()
        c.credentials(HTTP_X_WORKSPACE_ID=str(self.workspace.id))
        r = c.get("/api/v1/notifications/")
        self.assertEqual(r.status_code, 401)


class NotificationsSeenTest(TestCase):
    URL = "/api/v1/notifications/seen/"

    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@seen.test")
        cls.workspace = make_workspace(name="SeenWS", owner=cls.alice)
        cls.n1 = Notification.objects.create(
            user=cls.alice, title="n1", message="...",
        )
        cls.n2 = Notification.objects.create(
            user=cls.alice, title="n2", message="...",
        )
        cls.n3 = Notification.objects.create(
            user=cls.alice, title="n3", message="...",
        )

    def test_mark_specific_ids_seen(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            self.URL,
            {"seen": True, "ids": [str(self.n1.id), str(self.n2.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["updated"], 2)

        self.n1.refresh_from_db()
        self.n2.refresh_from_db()
        self.n3.refresh_from_db()
        self.assertTrue(self.n1.seen)
        self.assertTrue(self.n2.seen)
        self.assertFalse(self.n3.seen)

    def test_mark_all_seen_when_ids_omitted(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(self.URL, {"seen": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["updated"], 3)

    def test_mark_all_seen_when_ids_empty_list(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(self.URL, {"seen": True, "ids": []}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["updated"], 3)

    def test_unmark_specific(self):
        self.n1.seen = True
        self.n1.save(update_fields=["seen"])
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            self.URL,
            {"seen": False, "ids": [str(self.n1.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.n1.refresh_from_db()
        self.assertFalse(self.n1.seen)

    def test_other_users_ids_ignored(self):
        bob = make_user(email="bob@seen.test")
        bob_n = Notification.objects.create(user=bob, title="b", message="...")
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            self.URL,
            {"seen": True, "ids": [str(bob_n.id)]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["updated"], 0)
        bob_n.refresh_from_db()
        self.assertFalse(bob_n.seen)

    def test_no_op_when_already_seen(self):
        # All already unseen by default; flip the first, then re-flip the
        # same id to true → updated count is 1 the first time, 0 the second.
        c = api_client(user=self.alice, workspace=self.workspace)
        r1 = c.patch(
            self.URL,
            {"seen": True, "ids": [str(self.n1.id)]},
            format="json",
        )
        r2 = c.patch(
            self.URL,
            {"seen": True, "ids": [str(self.n1.id)]},
            format="json",
        )
        self.assertEqual(envelope(r1)["updated"], 1)
        self.assertEqual(envelope(r2)["updated"], 0)
