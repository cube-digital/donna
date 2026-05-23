"""
NotificationService — persistent alerts + realtime SSE delivery.

Static methods keep call sites short. ``create_alert`` writes a DB row
and publishes onto the right Redis pubsub channel based on ``scope``;
SSE views subscribe to those channels.

Channel scheme (see plans/10-realtime-layer.md):

- ``user-{uid}-notifications``              — personal events
- ``workspace-{wid}-notifications``         — workspace-wide events
- ``user-{uid}-workspace-{wid}-feed``       — user-scoped within workspace

The async ``create_sse_stream_multi`` runs under an ASGI server
(uvicorn). The sync ``publish``/``create_alert`` are safe from any
view, Celery task, or signal receiver.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from donna.core.cache import redis_manager

from .models import Notification, NotificationScope
from .schemas import NotificationPayload


logger = logging.getLogger(__name__)


def _channel_for_scope(
    scope: str, *, user_id: str, workspace_id: str | None
) -> str:
    """Pick the Redis pubsub channel for a notification."""
    if scope == NotificationScope.WORKSPACE:
        if not workspace_id:
            raise ValueError("scope=WORKSPACE requires workspace_id")
        return f"workspace-{workspace_id}-notifications"
    if scope == NotificationScope.USER_IN_WORKSPACE:
        if not workspace_id:
            raise ValueError("scope=USER_IN_WORKSPACE requires workspace_id")
        return f"user-{user_id}-workspace-{workspace_id}-feed"
    return f"user-{user_id}-notifications"


class NotificationService:
    # ── Persistent alerts ───────────────────────────────────────────────────
    @staticmethod
    def create_alert(
        user,
        title: str,
        message: str,
        notification_type: str = "info",
        data: dict[str, Any] | None = None,
        store: bool = True,
        workspace=None,
        scope: str = NotificationScope.USER,
    ) -> Notification | None:
        """
        Create + publish an alert.

        Args:
            user:               Recipient (required even for workspace scope — used for audit + DB row owner).
            title, message:     Human text.
            notification_type:  ``info`` | ``warning`` | ``error`` | ``success``.
            data:               Extra context, surfaced as ``context`` JSON + on SSE payload.
            store:              If False, skip DB persistence (ephemeral SSE only).
            workspace:          Required when ``scope`` != USER.
            scope:              ``NotificationScope`` value — drives the pubsub channel.
        """
        notification: Notification | None = None
        if store:
            notification = Notification.objects.create(
                user=user,
                title=title,
                message=message,
                type=notification_type,
                workspace=workspace,
                context=data or {},
                scope=scope,
            )

        ctx = data or {}
        payload = NotificationPayload(
            type="alert",
            message=message,
            data={
                "id":           str(notification.id) if notification else None,
                "task_name":    ctx.get("task_type") or ctx.get("event"),
                "title":        title,
                "status":       notification_type,
                "stored":       store,
                "scope":        scope,
                "workspace_id": str(workspace.id) if workspace else None,
                "context":      ctx,
            },
        )
        channel = _channel_for_scope(
            scope,
            user_id=str(user.id),
            workspace_id=str(workspace.id) if workspace else None,
        )
        redis_manager.publish_event(channel, json.dumps(payload.to_dict()))
        return notification

    @staticmethod
    def get_user_alerts(user, limit: int = 50) -> list[Notification]:
        return list(Notification.objects.for_user(user, limit))

    @staticmethod
    def get_unread_alerts(user) -> list[Notification]:
        return list(Notification.objects.unread_for_user(user))

    @staticmethod
    def get_unread_count(user) -> int:
        return Notification.objects.unread_for_user(user).count()

    @staticmethod
    def mark_as_read(user, notification_ids: list[str]) -> int:
        return Notification.objects.mark_as_read(user, notification_ids)

    @staticmethod
    def mark_all_read(user) -> int:
        return Notification.objects.mark_all_read(user)

    @staticmethod
    def set_seen(
        user,
        seen: bool,
        notification_ids: list[str] | None = None,
    ) -> int:
        """
        Flip ``seen`` for ``user``'s rows. ``notification_ids``
        empty/None applies to ALL of the user's rows currently not
        matching ``seen``. Returns the count actually changed.
        """
        return Notification.objects.set_seen(user, seen, notification_ids)

    # ── Ephemeral publish ───────────────────────────────────────────────────
    @staticmethod
    def publish(
        user_id: str,
        message: str,
        type: str = "info",
        data: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        scope: str = NotificationScope.USER,
    ) -> NotificationPayload:
        """
        Publish an ephemeral SSE payload. Channel selection mirrors
        ``create_alert``: pass ``workspace_id`` + ``scope`` for
        workspace-scoped pushes.
        """
        payload = NotificationPayload(type=type, message=message, data=data or {})
        channel = _channel_for_scope(scope, user_id=user_id, workspace_id=workspace_id)
        try:
            redis_manager.publish_event(channel, json.dumps(payload.to_dict()))
        except Exception as exc:                # noqa: BLE001
            logger.error("notification_publish_failed", extra={"channel": channel, "error": str(exc)})
        return payload

    @staticmethod
    def broadcast(
        user_ids: list[str],
        message: str,
        type: str = "info",
        data: dict[str, Any] | None = None,
    ) -> None:
        for uid in user_ids:
            NotificationService.publish(uid, message, type, data)

    # ── SSE channel naming helpers ──────────────────────────────────────────
    @staticmethod
    def get_channel_name(user_id: str) -> str:
        """Legacy single-channel name — kept for backward compatibility."""
        return f"user-{user_id}-notifications"

    @staticmethod
    def get_workspace_channel_name(workspace_id: str) -> str:
        return f"workspace-{workspace_id}-notifications"

    @staticmethod
    def get_user_workspace_feed_channel(user_id: str, workspace_id: str) -> str:
        return f"user-{user_id}-workspace-{workspace_id}-feed"

    # ── SSE stream ──────────────────────────────────────────────────────────
    @staticmethod
    async def create_sse_stream_multi(
        channels: list[str],
    ) -> AsyncGenerator[str, None]:
        """
        Subscribe to N Redis pubsub channels at once and multiplex onto
        one SSE stream. Caller wraps in ``StreamingHttpResponse`` with
        ``content_type='text/event-stream'``.
        """
        if not channels:
            yield NotificationService._format_sse(
                {"status": "error", "error": "no_channels"}
            )
            return

        async_client = await redis_manager.get_async_client()
        if async_client is None:
            yield NotificationService._format_sse(
                {"status": "error", "error": "redis_unavailable"}
            )
            return

        try:
            await async_client.ping()
        except Exception as exc:                # noqa: BLE001
            yield NotificationService._format_sse(
                {"status": "error", "error": f"redis_ping_failed: {exc}"}
            )
            return

        pubsub = None
        try:
            pubsub = async_client.pubsub()
            await pubsub.subscribe(*channels)

            yield NotificationService._format_sse(
                {"status": "connected", "channels": channels}
            )

            while True:
                try:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if msg and msg.get("type") == "message":
                        data = msg.get("data")
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        yield f"data: {data}\n\n"
                    await asyncio.sleep(0.1)
                except TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                except Exception as exc:        # noqa: BLE001
                    logger.error("sse_loop_error", extra={"error": str(exc)})
                    yield NotificationService._format_sse(
                        {"status": "error", "error": str(exc)}
                    )
                    await asyncio.sleep(1)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(*channels)
                    await pubsub.close()
                except Exception as exc:        # noqa: BLE001
                    logger.error("sse_cleanup_error", extra={"error": str(exc)})

    # Backward-compat shim — single channel.
    @staticmethod
    async def create_sse_stream(user_id: str) -> AsyncGenerator[str, None]:
        async for chunk in NotificationService.create_sse_stream_multi(
            [NotificationService.get_channel_name(user_id)]
        ):
            yield chunk

    @staticmethod
    def _format_sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"
