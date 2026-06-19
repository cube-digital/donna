"""Per-channel turn lock — Redis SET NX EX + Lua compare-and-delete.

Two concurrent messages in the same channel would race on agent
dispatch. The lock serializes turns; second dispatch raises TurnBusy
and the Celery task retries after a short backoff.

Token-safe release: the Lua script ensures only the holder can delete
the key — a lock that expires before release won't be wrongly deleted
by a later turn's finally-clause.
"""
from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

from donna.core.cache.redis_cache import redis_manager


class TurnBusy(RuntimeError):
    """Another turn is already running for this channel."""


_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


@contextmanager
def turn_lock(channel_id: str, timeout: int = 120):
    """Acquire (channel_id, token) lock; release on exit.

    Raises TurnBusy if another turn already holds the lock — caller
    retries (Celery `self.retry(countdown=…)`).
    """
    key = f"agent-turn:{channel_id}"
    token = uuid4().hex
    client = redis_manager.get_sync_client()

    acquired = client.set(key, token, nx=True, ex=timeout)
    if not acquired:
        raise TurnBusy(f"agent turn already in flight for channel {channel_id}")
    try:
        yield token
    finally:
        try:
            client.eval(_RELEASE_LUA, 1, key, token)
        except Exception:  # noqa: BLE001 — release best-effort
            pass
