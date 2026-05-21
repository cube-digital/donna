"""
Tiny Redis facade — sync ``publish_event`` + async client factory.

Sits between app code and the ``redis`` library so we have one place to
swap connection strategy, add metrics, or stub for tests. v1 reuses
``settings.CELERY_BROKER_URL`` as the broker for pubsub channels too;
splits out into a dedicated URL once load demands it.

Two consumers in v1:

- ``NotificationService.publish`` (sync, called from views + Celery
  tasks) → ``redis_manager.publish_event``
- ``NotificationService.create_sse_stream`` (async, called from the
  SSE view) → ``redis_manager.get_async_client``
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings


if TYPE_CHECKING:
    import redis
    import redis.asyncio as redis_async


logger = logging.getLogger(__name__)


def _redis_url() -> str:
    return getattr(settings, "REDIS_URL", None) or settings.CELERY_BROKER_URL


class _RedisManager:
    """Lazy singletons for the sync + async clients."""

    def __init__(self) -> None:
        self._sync_client: "redis.Redis | None" = None
        self._async_client: "redis_async.Redis | None" = None

    # ── Sync ────────────────────────────────────────────────────────────────
    def get_sync_client(self):
        if self._sync_client is None:
            import redis as _redis
            self._sync_client = _redis.Redis.from_url(
                _redis_url(), decode_responses=False
            )
        return self._sync_client

    def publish_event(self, channel: str, payload: str) -> int:
        """
        Publish ``payload`` on ``channel``. Returns the number of
        subscribers Redis claims received it (0 == no SSE listeners,
        non-fatal — message is discarded).
        """
        client = self.get_sync_client()
        try:
            return int(client.publish(channel, payload))
        except Exception as exc:                # noqa: BLE001
            logger.error("redis_publish_failed", extra={"channel": channel, "error": str(exc)})
            return 0

    # ── Presence helpers (sync) ─────────────────────────────────────────────
    def set_ex(self, key: str, value: str, ttl_seconds: int) -> bool:
        """``SET key value EX ttl`` — used for presence + ephemeral state."""
        client = self.get_sync_client()
        try:
            return bool(client.set(key, value, ex=ttl_seconds))
        except Exception as exc:                # noqa: BLE001
            logger.error("redis_set_ex_failed", extra={"key": key, "error": str(exc)})
            return False

    def get(self, key: str) -> bytes | None:
        client = self.get_sync_client()
        try:
            return client.get(key)
        except Exception as exc:                # noqa: BLE001
            logger.error("redis_get_failed", extra={"key": key, "error": str(exc)})
            return None

    def delete(self, key: str) -> int:
        client = self.get_sync_client()
        try:
            return int(client.delete(key))
        except Exception as exc:                # noqa: BLE001
            logger.error("redis_delete_failed", extra={"key": key, "error": str(exc)})
            return 0

    # ── Async ───────────────────────────────────────────────────────────────
    async def get_async_client(self):
        if self._async_client is None:
            import redis.asyncio as _redis_async
            self._async_client = _redis_async.from_url(
                _redis_url(), decode_responses=False
            )
        return self._async_client


redis_manager = _RedisManager()
