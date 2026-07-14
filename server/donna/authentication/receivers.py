"""
Signal receivers — send transactional auth emails via Django's email backend.

HTML + plaintext, rendered from ``authentication/emails/*`` and styled to
Donna's brand (see the workspace invitation emails). The frontend URL is built
from ``settings.WEB_REDIRECT_HOST`` plus a well-known path; rotate paths in one
place when the frontend routes change.

Wired in ``apps.AuthenticationConfig.ready``.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.dispatch import receiver
from django.template.loader import render_to_string

from .signals import (
    email_verify_request,
    reset_password_confirm,
    reset_password_recover,
)


logger = logging.getLogger(__name__)


def _frontend_url(path: str) -> str:
    host = (settings.WEB_REDIRECT_HOST or "").rstrip("/")
    return f"{host}{path}"


# ── Password recover ────────────────────────────────────────────────────────
@receiver(reset_password_recover)
def send_password_recover_email(sender, instance, reset_password_token, **kwargs):
    user = reset_password_token.user
    ctx = {
        "user_name": user.full_name or user.email,
        "reset_url": _frontend_url(f"/password/reset?token={reset_password_token.key}"),
    }
    send_mail(
        subject="Reset your Donna password",
        message=render_to_string("authentication/emails/password_recover.txt", ctx),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        html_message=render_to_string("authentication/emails/password_recover.html", ctx),
        fail_silently=False,
    )
    logger.info("password_recover_email_sent", extra={"user_id": str(user.id)})


# ── Password reset confirmation ─────────────────────────────────────────────
@receiver(reset_password_confirm)
def send_password_confirm_email(sender, user, **kwargs):
    ctx = {
        "user_name": user.full_name or user.email,
        "sign_in_url": _frontend_url("/auth"),
    }
    send_mail(
        subject="Your Donna password was changed",
        message=render_to_string("authentication/emails/password_changed.txt", ctx),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        html_message=render_to_string("authentication/emails/password_changed.html", ctx),
        fail_silently=False,
    )
    logger.info("password_confirm_email_sent", extra={"user_id": str(user.id)})


# ── Email verification ──────────────────────────────────────────────────────
@receiver(email_verify_request)
def send_email_verify_link(sender, instance, verification_token, **kwargs):
    user = verification_token.user
    link = _frontend_url(f"/email/verify?token={verification_token.key}")
    subject = "Verify your Donna email address"
    body = (
        f"Hi {user.full_name or user.email},\n\n"
        f"Click the link below to verify your email address:\n  {link}\n\n"
        f"The link expires in 7 days.\n"
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=False,
    )
    logger.info("email_verify_link_sent", extra={"user_id": str(user.id)})
