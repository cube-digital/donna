"""
Django admin for the User model. Custom UserAdmin tuned for Donna's
email-as-username model (no ``username`` field on ``User``).
"""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    UserChangeForm,
    UserCreationForm,
)

from .models import User


class DonnaUserCreationForm(UserCreationForm):
    """Creation form that uses ``email`` instead of ``username``."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name")


class DonnaUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = DonnaUserCreationForm
    form = DonnaUserChangeForm
    change_password_form = AdminPasswordChangeForm
    model = User

    list_display = (
        "email",
        "full_name",
        "is_active",
        "is_staff",
        "is_superuser",
        "email_verified",
        "date_joined",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "email_verified")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    readonly_fields = ("id", "last_login", "date_joined", "email_verified_at")

    fieldsets = (
        (None, {
            "fields": ("email", "password"),
        }),
        ("Profile", {
            "fields": ("full_name",),
        }),
        ("Email verification", {
            "fields": ("email_verified", "email_verified_at"),
        }),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        }),
        ("Audit", {
            "fields": ("id", "last_login", "date_joined"),
            "classes": ("collapse",),
        }),
    )

    # Used by the "Add user" form in admin — slim down to essentials.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "full_name",
                "password1",
                "password2",
                "is_staff",
                "is_superuser",
            ),
        }),
    )
