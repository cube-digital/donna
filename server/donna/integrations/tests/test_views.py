"""
Integrations endpoint coverage — list, retrieve, connect, disconnect,
subscription (Connection) CRUD, picker, scope-upgrade, OAuth callback,
webhook callback.

External vendor surfaces (token exchange, webhook signing) are mocked
at the connector handler boundary; we test the *Donna* code path, not
Google / Fathom / Notion. End-to-end OAuth + webhook delivery is its
own concern (manual + staged tests).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from donna.core.integrations import ProviderNotRegistered
from donna.core.tests.helpers import api_client, envelope
from donna.integrations.models import ClientCredentials, Connection, OAuthToken
from donna.integrations.services import RegistryService
from donna.users.tests.factories import make_user
from donna.workspaces.tests.factories import make_workspace


def _seed_fathom_client_credentials(*, workspace=None, enabled=True):
    """Create a ClientCredentials row for the fathom vendor.

    Fathom is the simplest registered connector — single-vendor, no
    shared OAuth provider. Tests targeting OAuth use this row.
    """
    return ClientCredentials.objects.create(
        slug="fathom",
        display_name="Fathom",
        workspace=workspace,
        is_enabled=enabled,
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/api/v1/integrations/fathom/oauth/callback",
        webhook_secret="test-webhook-secret",
    )


# ── IntegrationViewSet ──────────────────────────────────────────────────────
class IntegrationListRetrieveTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@int.test")
        cls.workspace = make_workspace(name="IntWS", owner=cls.alice)

    def test_list_returns_registered_connectors(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/")
        self.assertEqual(r.status_code, 200)
        slugs = {row["slug"] for row in envelope(r)}
        # At least the three default connectors are registered
        # (donna.integrations.apps.IntegrationsConfig.ready discovers them).
        self.assertIn("fathom", slugs)
        self.assertIn("gmail", slugs)
        self.assertIn("drive", slugs)

    def test_list_reports_unconfigured_when_no_client_credentials(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/")
        rows = {row["slug"]: row for row in envelope(r)}
        # No ClientCredentials seeded yet.
        self.assertFalse(rows["fathom"]["is_configured"])
        self.assertFalse(rows["fathom"]["is_connected"])

    def test_list_marks_configured_after_credentials_row(self):
        _seed_fathom_client_credentials()
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/")
        rows = {row["slug"]: row for row in envelope(r)}
        self.assertTrue(rows["fathom"]["is_configured"])

    def test_retrieve_returns_extended_payload(self):
        _seed_fathom_client_credentials()
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/fathom/")
        self.assertEqual(r.status_code, 200)
        body = envelope(r)
        self.assertEqual(body["slug"], "fathom")
        # Retrieve adds schema metadata that list omits.
        self.assertIn("token_scope", body)

    def test_retrieve_unknown_slug_404(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/totally-fake/")
        self.assertEqual(r.status_code, 404)


class IntegrationConnectTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@con.test")
        cls.workspace = make_workspace(name="ConWS", owner=cls.alice)

    def test_connect_503_when_not_configured(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post("/api/v1/integrations/fathom/connect/", {}, format="json")
        self.assertEqual(r.status_code, 503)

    def test_connect_404_for_unknown_slug(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post("/api/v1/integrations/nope/connect/", {}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_connect_returns_authorize_url_when_configured(self):
        _seed_fathom_client_credentials()
        # Mock the handler's URL builder so we don't talk to the upstream.
        with patch(
            "donna.integrations.connectors.fathom.provider.FathomProvider.oauth_handler"
        ) as mock_handler_factory:
            mock_handler = MagicMock()
            mock_handler.build_authorize_url.return_value = (
                "https://fathom.test/oauth?state=abc"
            )
            mock_handler_factory.return_value = mock_handler

            c = api_client(user=self.alice, workspace=self.workspace)
            r = c.post(
                "/api/v1/integrations/fathom/connect/",
                {"redirect_to": "/app/integrations"},
                format="json",
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            envelope(r)["authorize_url"],
            "https://fathom.test/oauth?state=abc",
        )


class IntegrationDisconnectTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@dis.test")
        cls.workspace = make_workspace(name="DisWS", owner=cls.alice)
        cls.credentials = _seed_fathom_client_credentials()

    def test_disconnect_404_when_no_token(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post("/api/v1/integrations/fathom/disconnect/", {}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_disconnect_removes_token_with_mocked_revoke(self):
        token = OAuthToken.objects.create(
            provider=self.credentials, user=self.alice,
            access_token="acc", refresh_token="ref", scope="all",
        )
        with patch(
            "donna.integrations.connectors.fathom.provider.FathomProvider.oauth_handler"
        ) as mock_handler_factory:
            mock_handler = MagicMock()
            mock_handler.revoke.return_value = None
            mock_handler_factory.return_value = mock_handler

            c = api_client(user=self.alice, workspace=self.workspace)
            r = c.post(
                "/api/v1/integrations/fathom/disconnect/", {}, format="json"
            )
        self.assertEqual(r.status_code, 204)
        self.assertFalse(OAuthToken.objects.filter(id=token.id).exists())


# ── ConnectionView (per-binding subscription) ───────────────────────────────
class ConnectionViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@conn.test")
        cls.workspace = make_workspace(name="ConnWS", owner=cls.alice)
        cls.credentials = _seed_fathom_client_credentials()
        cls.token = OAuthToken.objects.create(
            provider=cls.credentials, user=cls.alice,
            access_token="acc",
        )
        cls.connection = Connection.objects.create(
            workspace=cls.workspace, user=cls.alice,
            provider_slug="fathom", token=cls.token,
            config={"foo": "bar"},
        )

    def test_get_returns_connection(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.get("/api/v1/integrations/fathom/subscription/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["id"], str(self.connection.id))
        self.assertEqual(envelope(r)["config"]["foo"], "bar")

    def test_get_404_when_no_connection(self):
        other_user = make_user(email="other@conn.test")
        c = api_client(user=other_user, workspace=self.workspace)
        r = c.get("/api/v1/integrations/fathom/subscription/")
        self.assertEqual(r.status_code, 404)

    def test_patch_non_object_config_400(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.patch(
            "/api/v1/integrations/fathom/subscription/",
            {"config": "not-a-dict"}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    # NOTE: validate_config is connector-specific (defined on Gmail/Drive,
    # absent on Fathom — see ``donna.core.integrations.provider``
    # ``IntegrationProvider`` is a ``Protocol`` with no method body). Per-
    # connector validation behavior is tested in the connector's own
    # tests; here we only assert the *view* contract (non-object → 400).

    def test_delete_removes_connection(self):
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.delete("/api/v1/integrations/fathom/subscription/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(
            Connection.objects.filter(id=self.connection.id).exists()
        )


# ── ConnectionPickerView ────────────────────────────────────────────────────
class ConnectionPickerTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@pick.test")
        cls.workspace = make_workspace(name="PickWS", owner=cls.alice)
        cls.credentials = _seed_fathom_client_credentials()
        cls.token = OAuthToken.objects.create(
            provider=cls.credentials, user=cls.alice, access_token="acc",
        )
        cls.connection = Connection.objects.create(
            workspace=cls.workspace, user=cls.alice,
            provider_slug="fathom", token=cls.token,
        )

    def test_picker_404_when_connection_missing(self):
        # No connection for this user — picker view still 404s upfront.
        outsider = make_user(email="outsider@pick.test")
        c = api_client(user=outsider, workspace=self.workspace)
        r = c.get("/api/v1/integrations/fathom/subscription/picker/teams")
        self.assertEqual(r.status_code, 404)

    # NOTE: picker happy-path is connector-specific (the Fathom
    # connector doesn't implement picker; Drive/Gmail/Notion do). Per-
    # connector picker tests belong in their own connector test files.


class ConnectionUpgradeScopeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@up.test")
        cls.workspace = make_workspace(name="UpWS", owner=cls.alice)
        cls.credentials = _seed_fathom_client_credentials()
        cls.token = OAuthToken.objects.create(
            provider=cls.credentials, user=cls.alice, access_token="acc",
        )
        cls.connection = Connection.objects.create(
            workspace=cls.workspace, user=cls.alice,
            provider_slug="fathom", token=cls.token,
        )

    def test_upgrade_404_when_connector_doesnt_support(self):
        # Fathom doesn't define build_scope_upgrade_url.
        c = api_client(user=self.alice, workspace=self.workspace)
        r = c.post(
            "/api/v1/integrations/fathom/subscription/upgrade-scope",
            {}, format="json",
        )
        self.assertEqual(r.status_code, 404)


# ── Webhook callback ────────────────────────────────────────────────────────
class WebhookCallbackTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@wh.test")
        cls.workspace = make_workspace(name="WhWS", owner=cls.alice)

    def test_webhook_unknown_slug_404(self):
        c = api_client()  # no auth
        r = c.post("/api/v1/integrations/nope/webhook/callback", b"{}",
                   content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_webhook_invalid_payload_400(self):
        # Webhook view instantiates the handler, which reads
        # ClientCredentials. Seed minimal creds so the parse failure
        # path is the one we exercise.
        _seed_fathom_client_credentials()
        c = api_client()
        r = c.post(
            "/api/v1/integrations/fathom/webhook/callback",
            b"not-json-text",
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    # NOTE: end-to-end signature-verification requires the connector's
    # private webhook secret (Fathom stores per-Connection secrets on
    # ``Connection.state["webhook"]["secret"]``). That handshake is
    # tested in the connector's own test module; this view-level suite
    # only covers parse errors + slug lookup.


# ── OAuth callback ──────────────────────────────────────────────────────────
class OAuthCallbackTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@oc.test")
        cls.workspace = make_workspace(name="OcWS", owner=cls.alice)

    def test_callback_missing_code_or_state_returns_400(self):
        c = api_client()
        r = c.get("/api/v1/integrations/fathom/oauth/callback")
        self.assertEqual(r.status_code, 400)

    def test_callback_upstream_error_redirects(self):
        c = api_client()
        r = c.get(
            "/api/v1/integrations/fathom/oauth/callback"
            "?error=access_denied&error_description=user+declined"
        )
        self.assertEqual(r.status_code, 302)
        self.assertIn("error", r["Location"])

    def test_callback_invalid_state_returns_400(self):
        c = api_client()
        r = c.get(
            "/api/v1/integrations/fathom/oauth/callback"
            "?code=test_code&state=not-a-signed-state"
        )
        self.assertEqual(r.status_code, 400)


# ── RegistryService (direct) ────────────────────────────────────────────────
class RegistryServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = make_user(email="alice@reg.test")
        cls.workspace = make_workspace(name="RegWS", owner=cls.alice)

    def test_list_for_workspace_returns_all_registered(self):
        svc = RegistryService(current_user=self.alice, company=self.workspace)
        statuses = svc.list_for_workspace(self.workspace)
        slugs = {s.slug for s in statuses}
        self.assertIn("fathom", slugs)
        self.assertIn("gmail", slugs)

    def test_get_status_unknown_slug_raises(self):
        svc = RegistryService(current_user=self.alice, company=self.workspace)
        with self.assertRaises(ProviderNotRegistered):
            svc.get_status(self.workspace, "totally-fake-slug")

    def test_get_status_reflects_connection(self):
        creds = _seed_fathom_client_credentials()
        OAuthToken.objects.create(
            provider=creds, user=self.alice, access_token="acc",
        )
        svc = RegistryService(current_user=self.alice, company=self.workspace)
        status_dto = svc.get_status(self.workspace, "fathom")
        self.assertTrue(status_dto.is_configured)
        self.assertTrue(status_dto.is_connected)
