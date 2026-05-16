"""
Core database utilities (Django).

Exports get_postgresql_session for FastAPI dependencies that expect
a SQLAlchemy-style session. get_qdrant_client is a stub returning None
(Qdrant removed; callers should use Postgres).
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from django.db import connection


def get_qdrant_client() -> Any:
    """Stub: Qdrant removed. Returns None so Depends() and 'if client' still work."""
    return None


@contextmanager
def get_postgresql_session() -> Generator[None, None, None]:
    """
    Yield a Django DB connection for use as a postgres session context.

    Used by code that expects a session-like interface; wraps Django's
    connection so that code using it does not fail at import.
    """
    yield connection
