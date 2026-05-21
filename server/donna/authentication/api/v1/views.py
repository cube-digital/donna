"""
Authentication views — signup, password reset, email verify, Google login.

All endpoints sit under ``/api/auth/`` and are public (no
``X-Workspace-Id`` requirement; ``WorkspaceMiddleware.IGNORED_PATHS``
already covers the prefix). JWT-protected endpoints flip
``permission_classes`` to ``IsAuthenticated``.
"""
from __future__ import annotations

import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from donna.users.models import User

from ...models import EmailVerificationToken, ResetPasswordToken
from ...services import AuthService
from ...settings import api_settings
from ...signals import (
    email_verify_request,
    reset_password_confirm,
    reset_password_recover,
)
from .serializers import (
    CustomTokenObtainPairSerializer,
    EmailVerifyConfirmSerializer,
    PasswordRecoverSerializer,
    PasswordResetSerializer,
    SignUpSerializer,
)


logger = logging.getLogger(__name__)


# ── Signup / Signin ──────────────────────────────────────────────────────────
class SignUpView(generics.GenericAPIView):
    """Create a new email/password user. Returns 201 on success."""

    serializer_class = SignUpSerializer
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        User.objects.create_user(**serializer.validated_data)
        return Response(
            {"message": "User created successfully"},
            status=status.HTTP_201_CREATED,
        )


class SignInView(TokenObtainPairView):
    """JWT signin — wraps simplejwt's view with our custom serializer."""

    serializer_class = CustomTokenObtainPairSerializer


# ── Password reset (3 steps) ─────────────────────────────────────────────────
class ResetPasswordView(generics.GenericAPIView):
    """Step 1 — request a reset link emailed to the user."""

    serializer_class = PasswordRecoverSerializer
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response(
                {"detail": "No user found for this email address."},
                status=status.HTTP_404_NOT_FOUND,
            )

        active = user.reset_password_tokens.filter(expiry_at__gt=timezone.now())
        if active.count() >= api_settings.RESET_PASSWORD_TOKEN_LIMIT_PER_USER:
            return Response(
                {"detail": "Maximum password reset requests reached. Try again later."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token = ResetPasswordToken.objects.create(user=user)
        reset_password_recover.send(
            sender=self.__class__, instance=self, reset_password_token=token
        )
        return Response(
            {"detail": "Password reset link sent."},
            status=status.HTTP_201_CREATED,
        )


class ResetPasswordValidationView(generics.GenericAPIView):
    """Step 2 — frontend checks the token is valid before showing the form."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, token: str):
        tok = ResetPasswordToken.objects.filter(key=token).first()
        if tok is None:
            return Response({"status": "Not Found"}, status=status.HTTP_404_NOT_FOUND)
        if tok.has_expired():
            return Response({"status": "Expired"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"status": "OK"})


class ResetPasswordConfirmView(generics.GenericAPIView):
    """Step 3 — write the new password and consume the token."""

    serializer_class = PasswordResetSerializer
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_key = serializer.validated_data["token"]
        new_password = serializer.validated_data["password"]

        tok = ResetPasswordToken.objects.filter(key=token_key).first()
        if tok is None:
            return Response({"status": "Not Found"}, status=status.HTTP_404_NOT_FOUND)
        if tok.has_expired():
            return Response({"status": "Expired"}, status=status.HTTP_404_NOT_FOUND)

        try:
            validate_password(new_password, user=tok.user)
        except DjangoValidationError as err:
            return Response({"detail": list(err.messages)}, status=status.HTTP_400_BAD_REQUEST)

        tok.user.set_password(new_password)
        tok.user.save(update_fields=["password"])

        reset_password_confirm.send(sender=self.__class__, user=tok.user)
        ResetPasswordToken.objects.filter(user=tok.user).delete()
        ResetPasswordToken.objects.clean_expired_tokens()

        return Response({"status": "OK"})


# ── Email verification ───────────────────────────────────────────────────────
class EmailVerifyRequestView(generics.GenericAPIView):
    """Authed user requests a verify email be sent to their address."""

    authentication_classes_default = None     # use DRF default (simplejwt)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.email_verified:
            return Response(
                {"status": "AlreadyVerified"},
                status=status.HTTP_200_OK,
            )

        active = user.email_verification_tokens.filter(
            expiry_at__gt=timezone.now(),
            consumed_at__isnull=True,
        )
        if active.count() >= api_settings.EMAIL_VERIFY_TOKEN_LIMIT_PER_USER:
            return Response(
                {"detail": "Maximum verification requests reached. Try again later."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token = EmailVerificationToken.objects.create(user=user)
        email_verify_request.send(
            sender=self.__class__, instance=self, verification_token=token
        )
        return Response({"status": "Sent"}, status=status.HTTP_201_CREATED)


class EmailVerifyConfirmView(generics.GenericAPIView):
    """Public — token-only confirmation. Flips ``User.email_verified=True``."""

    serializer_class = EmailVerifyConfirmSerializer
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, token: str):
        tok = EmailVerificationToken.objects.filter(key=token).first()
        if tok is None:
            return Response({"status": "Not Found"}, status=status.HTTP_404_NOT_FOUND)
        if tok.is_consumed():
            return Response({"status": "AlreadyConsumed"})
        if tok.has_expired():
            return Response({"status": "Expired"}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        tok.consumed_at = now
        tok.save(update_fields=["consumed_at", "updated_at"])

        user = tok.user
        if not user.email_verified:
            user.email_verified = True
            user.email_verified_at = now
            user.save(update_fields=["email_verified", "email_verified_at"])

        EmailVerificationToken.objects.clean_expired_tokens()
        return Response({"status": "OK"})


# ── Google login ─────────────────────────────────────────────────────────────
class GoogleLoginView(generics.GenericAPIView):
    """Return the Google authorize URL for the frontend to redirect to."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        auth_service = AuthService()
        url = auth_service.get_authorization_url("google_login", {"type": "login"})
        return Response({"authorization_url": url})


class GoogleCallbackView(generics.GenericAPIView):
    """OAuth callback — exchanges code, issues JWT, 302s to frontend."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        auth_service = AuthService()
        result = auth_service.handle_oauth_callback("google_login", request)
        return redirect(result["redirect_url"])
