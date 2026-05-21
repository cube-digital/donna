"""
Chat HTTP REST routes — mounted under ``/api/v1/chat/`` by
``donna/urls.py``.

WS routes live in ``donna/chat/routing.py`` and are mounted by
``donna/asgi.py``.
"""
from __future__ import annotations

from django.urls import path

from .api.v1.views import (
    ChannelDetailView,
    ChannelListCreateView,
    ChannelMessageListCreateView,
    ChannelReadStateView,
    DMOpenView,
    MessageDetailView,
)


urlpatterns = [
    path("channels/",                              ChannelListCreateView.as_view(),       name="chat-channel-list"),
    path("channels/<uuid:id>/",                    ChannelDetailView.as_view(),           name="chat-channel-detail"),
    path("channels/<uuid:id>/messages/",           ChannelMessageListCreateView.as_view(),name="chat-channel-messages"),
    path("channels/<uuid:id>/read-state/",         ChannelReadStateView.as_view(),        name="chat-channel-read-state"),
    path("messages/<uuid:id>/",                    MessageDetailView.as_view(),           name="chat-message-detail"),
    path("dms/",                                   DMOpenView.as_view(),                  name="chat-dm-open"),
]
