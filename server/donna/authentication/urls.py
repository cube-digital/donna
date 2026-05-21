"""
Authentication app URL routes.

Mounted under ``/api/auth/`` by ``donna/urls.py``. The prefix is already
listed in ``WorkspaceMiddleware.IGNORED_PATHS`` so these endpoints skip
the workspace-header requirement.
"""
from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenRefreshView,
)

from .api.v1.views import (
    EmailVerifyConfirmView,
    EmailVerifyRequestView,
    GoogleCallbackView,
    GoogleLoginView,
    ResetPasswordConfirmView,
    ResetPasswordValidationView,
    ResetPasswordView,
    SignInView,
    SignUpView,
)


urlpatterns = [
    # Signup / signin / token lifecycle
    path("signup",          SignUpView.as_view(),         name="auth-signup"),
    path("signin",          SignInView.as_view(),         name="auth-signin"),
    path("token/refresh",   TokenRefreshView.as_view(),   name="auth-token-refresh"),
    path("token/blacklist", TokenBlacklistView.as_view(), name="auth-token-blacklist"),
    path("logout",          TokenBlacklistView.as_view(), name="auth-logout"),

    # Password reset (3 steps)
    path("password/recover",              ResetPasswordView.as_view(),           name="auth-password-recover"),
    path("password/validate/<str:token>", ResetPasswordValidationView.as_view(), name="auth-password-validate"),
    path("password/confirm",              ResetPasswordConfirmView.as_view(),    name="auth-password-confirm"),

    # Email verification
    path("email/verify/request",             EmailVerifyRequestView.as_view(), name="auth-email-verify-request"),
    path("email/verify/confirm/<str:token>", EmailVerifyConfirmView.as_view(), name="auth-email-verify-confirm"),

    # Google login
    path("google/login",    GoogleLoginView.as_view(),    name="auth-google-login"),
    path("google/callback", GoogleCallbackView.as_view(), name="auth-google-callback"),
]
