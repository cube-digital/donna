"""
User factories — tiny helpers, no ``factory_boy`` dep.

Each call creates a fresh user with a unique email so tests don't bleed
across each other when run with ``--keepdb`` or against a shared
database.
"""
from __future__ import annotations

import uuid

from donna.users.models import User


def make_user(
    *,
    email: str | None = None,
    password: str = "S3curePass!2026",
    full_name: str | None = None,
) -> User:
    """Create + return a User. Email auto-generates if omitted."""
    if email is None:
        email = f"u-{uuid.uuid4().hex[:8]}@test.local"
    if full_name is None:
        full_name = email.split("@", 1)[0].title()
    return User.objects.create_user(
        email=email, password=password, full_name=full_name
    )
