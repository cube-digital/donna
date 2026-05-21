"""
Serializers for the authentication API.

Plain DRF serializers, no model bindings — the request/response shapes
diverge enough from the underlying models to make ``ModelSerializer``
more trouble than it's worth.
"""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from donna.users.models import User


class SignUpSerializer(serializers.Serializer):
    """Email + password + optional full name. Returns a created user."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("User with this email already exists.")
        return value.lower()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Extend simplejwt's token response with a frontend hint.

    The frontend uses ``redirect_uri`` to decide where to send the user
    after sign-in (e.g., onboarding vs. dashboard). v1 always returns
    ``/`` because there's no onboarding flow yet — kept here so adding
    one later is a one-line change.
    """

    def validate(self, attrs):
        data = super().validate(attrs)
        data["redirect_uri"] = "/"
        return data


class PasswordRecoverSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(label="New Password")


class EmailVerifyConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
