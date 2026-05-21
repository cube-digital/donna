"""
WebSocket URL routing for the chat / agent realtime layer.

Mounted by ``donna/asgi.py`` under the ``websocket`` protocol of the
``ProtocolTypeRouter``. JWT auth happens in
``donna.chat.auth.SubprotocolJWTAuthMiddleware`` before the consumer
runs.

URLs:

    /ws/                          → ChatConsumer (one per user; all chat/DM/presence)
    /ws/agent/{run_id}/           → AgentStreamConsumer (token streaming per agent run)
"""
from __future__ import annotations

from django.urls import re_path

from .consumers import AgentStreamConsumer, ChatConsumer


websocket_urlpatterns = [
    re_path(r"^ws/$",                              ChatConsumer.as_asgi()),
    re_path(r"^ws/agent/(?P<run_id>[^/]+)/?$",     AgentStreamConsumer.as_asgi()),
]
