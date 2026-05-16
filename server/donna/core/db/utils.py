import logging
import random
import time
from functools import wraps

from django.contrib.auth import get_user_model
from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)

_RETRYABLE_FRAGMENTS = (
    "remaining connection slots",
    "too many clients",
    "too many connections",
    "could not connect to server",
    "connection refused",
    "connection timed out",
    "server closed the connection unexpectedly",
    "ssl connection has been closed unexpectedly",
    "the database system is starting up",
    "connection already closed",
    "connection is closed",
)


def _is_retryable_db_error(exc: Exception) -> bool:
    """Return ``True`` when *exc* looks like a transient connection error."""
    msg = str(exc).lower()
    return any(frag in msg for frag in _RETRYABLE_FRAGMENTS)


def db_retry(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
):
    """
    Decorator: retry a function on transient DB connection errors.

    Uses exponential back-off with jitter.  Before each retry the
    current thread's Django DB connections are closed so Django opens
    a fresh socket on the next ORM call.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except OperationalError as exc:
                    if (
                        not _is_retryable_db_error(exc)
                        or attempt >= max_retries
                    ):
                        raise
                    last_exc = exc
                    delay = min(
                        base_delay * (2 ** attempt)
                        + random.uniform(0, 1),
                        max_delay,
                    )
                    logger.warning(
                        "DB connection error (attempt %d/%d), "
                        "retrying in %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    connections.close_all()
                    time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


def db_can_connect(db_alias: str = "default") -> bool:
    try:
        get_user_model().objects.using(db_alias).only("pk").first()
        return True
    except OperationalError:
        return False
