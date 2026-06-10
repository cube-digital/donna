"""
Authentication endpoint coverage — signup/signin edges, token refresh,
blacklist + logout, password reset 3-step (with rate-limit), email
verification request + confirm, Google OAuth start.

Google callback is integration-only (mocks the OAuth provider) — it
goes through ``AuthService.handle_oauth_callback`` which talks to
Google. Tested separately with ``unittest.mock``.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from donna.authentication.models import EmailVerificationToken, ResetPasswordToken
from donna.authentication.settings import api_settings
from donna.core.tests.helpers import api_client, envelope
from donna.users.tests.factories import make_user


# ── Signup ──────────────────────────────────────────────────────────────────
class SignUpTest(TestCase):
    URL = "/api/auth/signup"

    def test_creates_user(self):
        c = api_client()
        r = c.post(
            self.URL,
            {"email": "fresh@auth.test", "password": "S3cure!2026P", "full_name": "Fresh"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)

        from donna.users.models import User
        self.assertTrue(User.objects.filter(email="fresh@auth.test").exists())

    def test_duplicate_email_rejected(self):
        make_user(email="dup@auth.test")
        c = api_client()
        r = c.post(
            self.URL,
            {"email": "dup@auth.test", "password": "S3cure!2026P"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_invalid_email_format(self):
        c = api_client()
        r = c.post(
            self.URL,
            {"email": "not-an-email", "password": "S3cure!2026P"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_weak_password_rejected(self):
        c = api_client()
        r = c.post(
            self.URL,
            {"email": "weak@auth.test", "password": "123"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_missing_password(self):
        c = api_client()
        r = c.post(self.URL, {"email": "x@auth.test"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_email_normalized_to_lowercase(self):
        c = api_client()
        c.post(
            self.URL,
            {"email": "Mixed@AUTH.test", "password": "S3cure!2026P"},
            format="json",
        )
        from donna.users.models import User
        # Validator on the serializer lowercases.
        self.assertTrue(User.objects.filter(email="mixed@auth.test").exists())


# ── Signin / refresh / blacklist ────────────────────────────────────────────
class SignInTest(TestCase):
    URL_IN = "/api/auth/signin"

    def setUp(self):
        self.user = make_user(email="signin@auth.test", password="S3cure!2026P")

    def test_signin_returns_access_and_refresh(self):
        c = api_client()
        r = c.post(
            self.URL_IN,
            {"email": "signin@auth.test", "password": "S3cure!2026P"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        body = envelope(r)
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertEqual(body["redirect_uri"], "/")

    def test_signin_bad_password_401(self):
        c = api_client()
        r = c.post(
            self.URL_IN,
            {"email": "signin@auth.test", "password": "wrong"},
            format="json",
        )
        self.assertEqual(r.status_code, 401)

    def test_signin_nonexistent_user_401(self):
        c = api_client()
        r = c.post(
            self.URL_IN,
            {"email": "no-such@auth.test", "password": "S3cure!2026P"},
            format="json",
        )
        self.assertEqual(r.status_code, 401)


class TokenRefreshTest(TestCase):
    URL_REFRESH = "/api/auth/token/refresh"
    URL_BLACKLIST = "/api/auth/token/blacklist"

    def setUp(self):
        self.user = make_user(email="refresh@auth.test", password="S3cure!2026P")

    def _signin(self):
        c = api_client()
        r = c.post(
            "/api/auth/signin",
            {"email": "refresh@auth.test", "password": "S3cure!2026P"},
            format="json",
        )
        return envelope(r)

    def test_refresh_with_valid_refresh_returns_new_access(self):
        tokens = self._signin()
        c = api_client()
        r = c.post(self.URL_REFRESH, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", envelope(r))

    def test_refresh_with_invalid_token_401(self):
        c = api_client()
        r = c.post(self.URL_REFRESH, {"refresh": "not-a-valid-token"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_blacklist_invalidates_refresh(self):
        """
        ``POST /api/auth/token/blacklist`` blacklists the refresh token
        so a subsequent ``POST /api/auth/token/refresh`` with the same
        token is rejected. Requires
        ``rest_framework_simplejwt.token_blacklist`` in INSTALLED_APPS
        and ``BLACKLIST_AFTER_ROTATION: True`` in SIMPLE_JWT.
        """
        tokens = self._signin()
        c = api_client()
        r = c.post(self.URL_BLACKLIST, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)
        # The blacklisted refresh can no longer mint a new access token.
        r2 = c.post(self.URL_REFRESH, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r2.status_code, 401)

    def test_logout_invalidates_refresh(self):
        """``/api/auth/logout`` is an alias for blacklist; same semantics."""
        tokens = self._signin()
        c = api_client()
        r = c.post("/api/auth/logout", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)
        r2 = c.post(self.URL_REFRESH, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r2.status_code, 401)

    def test_refresh_rotates_and_blacklists_old_token(self):
        """
        With ``ROTATE_REFRESH_TOKENS`` + ``BLACKLIST_AFTER_ROTATION``,
        every successful refresh issues a new refresh token AND
        blacklists the previous one — replaying the old token must
        fail.
        """
        tokens = self._signin()
        c = api_client()
        r = c.post(
            self.URL_REFRESH, {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(r.status_code, 200)
        new_refresh = envelope(r).get("refresh")
        self.assertIsNotNone(new_refresh, "rotation should issue a new refresh token")
        self.assertNotEqual(new_refresh, tokens["refresh"])

        # Old refresh is now blacklisted.
        replay = c.post(
            self.URL_REFRESH, {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(replay.status_code, 401)
        # New refresh still works.
        fresh = c.post(
            self.URL_REFRESH, {"refresh": new_refresh}, format="json"
        )
        self.assertEqual(fresh.status_code, 200)

    def test_logout_is_alias_for_blacklist(self):
        tokens = self._signin()
        c = api_client()
        r = c.post("/api/auth/logout", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)


# ── Password reset 3-step ───────────────────────────────────────────────────
class PasswordResetTest(TestCase):
    URL_RECOVER = "/api/auth/password/recover"
    URL_CONFIRM = "/api/auth/password/confirm"

    def setUp(self):
        self.user = make_user(email="reset@auth.test", password="OldP@ssw0rd!")

    def test_recover_creates_token_for_known_email(self):
        c = api_client()
        r = c.post(self.URL_RECOVER, {"email": "reset@auth.test"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            ResetPasswordToken.objects.filter(user=self.user).count(), 1
        )

    def test_recover_unknown_email_returns_404(self):
        c = api_client()
        r = c.post(self.URL_RECOVER, {"email": "nobody@auth.test"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_validate_endpoint_recognises_active_token(self):
        token = ResetPasswordToken.objects.create(user=self.user)
        c = api_client()
        r = c.get(f"/api/auth/password/validate/{token.key}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["status"], "OK")

    def test_validate_endpoint_404_unknown_token(self):
        c = api_client()
        r = c.get("/api/auth/password/validate/not-a-token-xxx")
        self.assertEqual(r.status_code, 404)

    def test_validate_endpoint_404_expired_token(self):
        token = ResetPasswordToken.objects.create(user=self.user)
        token.expiry_at = timezone.now() - timedelta(hours=1)
        token.save(update_fields=["expiry_at"])
        c = api_client()
        r = c.get(f"/api/auth/password/validate/{token.key}")
        self.assertEqual(r.status_code, 404)

    def test_confirm_sets_new_password_and_consumes_token(self):
        token = ResetPasswordToken.objects.create(user=self.user)
        c = api_client()
        r = c.post(
            self.URL_CONFIRM,
            {"token": token.key, "password": "N3wS3cure!2026"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        # All tokens for this user are consumed.
        self.assertEqual(
            ResetPasswordToken.objects.filter(user=self.user).count(), 0
        )
        # The new password actually works.
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("N3wS3cure!2026"))

    def test_confirm_rejects_unknown_token(self):
        c = api_client()
        r = c.post(
            self.URL_CONFIRM,
            {"token": "not-a-token-xxx", "password": "N3wS3cure!2026"},
            format="json",
        )
        self.assertEqual(r.status_code, 404)

    def test_confirm_rejects_expired_token(self):
        token = ResetPasswordToken.objects.create(user=self.user)
        token.expiry_at = timezone.now() - timedelta(hours=1)
        token.save(update_fields=["expiry_at"])
        c = api_client()
        r = c.post(
            self.URL_CONFIRM,
            {"token": token.key, "password": "N3wS3cure!2026"},
            format="json",
        )
        self.assertEqual(r.status_code, 404)

    def test_confirm_rejects_weak_password(self):
        token = ResetPasswordToken.objects.create(user=self.user)
        c = api_client()
        r = c.post(
            self.URL_CONFIRM,
            {"token": token.key, "password": "123"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_rate_limit_kicks_in_after_max_tokens(self):
        # Max-out the active token count.
        for _ in range(api_settings.RESET_PASSWORD_TOKEN_LIMIT_PER_USER):
            ResetPasswordToken.objects.create(user=self.user)
        c = api_client()
        r = c.post(self.URL_RECOVER, {"email": "reset@auth.test"}, format="json")
        self.assertEqual(r.status_code, 403)


# ── Email verification ──────────────────────────────────────────────────────
class EmailVerifyTest(TestCase):
    URL_REQUEST = "/api/auth/email/verify/request"

    def setUp(self):
        self.user = make_user(email="ev@auth.test", password="S3cure!2026P")

    def test_request_unauthenticated_returns_401(self):
        c = api_client()  # no auth
        r = c.post(self.URL_REQUEST)
        self.assertEqual(r.status_code, 401)

    def test_request_authed_creates_token(self):
        c = api_client(user=self.user)
        r = c.post(self.URL_REQUEST)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(envelope(r)["status"], "Sent")
        self.assertEqual(
            EmailVerificationToken.objects.filter(user=self.user).count(), 1
        )

    def test_request_already_verified_short_circuits(self):
        self.user.email_verified = True
        self.user.email_verified_at = timezone.now()
        self.user.save()
        c = api_client(user=self.user)
        r = c.post(self.URL_REQUEST)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["status"], "AlreadyVerified")

    def test_request_rate_limited_after_max_tokens(self):
        for _ in range(api_settings.EMAIL_VERIFY_TOKEN_LIMIT_PER_USER):
            EmailVerificationToken.objects.create(user=self.user)
        c = api_client(user=self.user)
        r = c.post(self.URL_REQUEST)
        self.assertEqual(r.status_code, 403)

    def test_confirm_flips_email_verified(self):
        token = EmailVerificationToken.objects.create(user=self.user)
        c = api_client()
        r = c.get(f"/api/auth/email/verify/confirm/{token.key}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["status"], "OK")
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertIsNotNone(self.user.email_verified_at)

    def test_confirm_unknown_token_404(self):
        c = api_client()
        r = c.get("/api/auth/email/verify/confirm/not-a-token-xxx")
        self.assertEqual(r.status_code, 404)

    def test_confirm_expired_token_404(self):
        token = EmailVerificationToken.objects.create(user=self.user)
        token.expiry_at = timezone.now() - timedelta(hours=1)
        token.save(update_fields=["expiry_at"])
        c = api_client()
        r = c.get(f"/api/auth/email/verify/confirm/{token.key}")
        self.assertEqual(r.status_code, 404)

    def test_confirm_already_consumed_returns_status(self):
        token = EmailVerificationToken.objects.create(user=self.user)
        token.consumed_at = timezone.now()
        token.save(update_fields=["consumed_at"])
        c = api_client()
        r = c.get(f"/api/auth/email/verify/confirm/{token.key}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(envelope(r)["status"], "AlreadyConsumed")


# ── Google OAuth ────────────────────────────────────────────────────────────
class GoogleOAuthTest(TestCase):
    """Mocks AuthService — we just verify wiring; provider talk is its own concern."""

    def test_login_returns_authorization_url(self):
        with patch(
            "donna.authentication.api.v1.views.AuthService"
        ) as MockAuthService:
            MockAuthService.return_value.get_authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth?xyz"
            )
            c = api_client()
            r = c.get("/api/auth/google/login")
            self.assertEqual(r.status_code, 200)
            self.assertIn("authorization_url", envelope(r))

    def test_callback_redirects_to_frontend(self):
        with patch(
            "donna.authentication.api.v1.views.AuthService"
        ) as MockAuthService:
            MockAuthService.return_value.handle_oauth_callback.return_value = {
                "redirect_url": "http://localhost:5173/app/?token=abc",
            }
            c = api_client()
            r = c.get("/api/auth/google/callback?code=test_code&state=test_state")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/app/", r["Location"])
