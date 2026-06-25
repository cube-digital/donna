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
    ChannelDocumentDetailView,
    ChannelDocumentsView,
    ChannelListCreateView,
    ChannelMemberRemoveView,
    ChannelMembersView,
    ChannelMessageListCreateView,
    ChannelPinView,
    ChannelReadStateView,
    DMOpenView,
    GroupDMOpenView,
    MessageDetailView,
    MessageReactionsView,
    MessageRepliesView,
)


urlpatterns = [
    path("channels/",                              ChannelListCreateView.as_view(),       name="chat-channel-list"),
    path("channels/<uuid:id>/",                    ChannelDetailView.as_view(),           name="chat-channel-detail"),
    path("channels/<uuid:id>/messages/",           ChannelMessageListCreateView.as_view(),name="chat-channel-messages"),
    path("channels/<uuid:id>/members/",            ChannelMembersView.as_view(),          name="chat-channel-members"),
    path("channels/<uuid:id>/members/<uuid:user_id>/", ChannelMemberRemoveView.as_view(), name="chat-channel-member-remove"),
    path("channels/<uuid:id>/read-state/",         ChannelReadStateView.as_view(),        name="chat-channel-read-state"),
    path("channels/<uuid:id>/documents/",          ChannelDocumentsView.as_view(),        name="chat-channel-documents"),
    path("channels/<uuid:id>/documents/<uuid:doc_id>/", ChannelDocumentDetailView.as_view(), name="chat-channel-document-detail"),
    path("channels/<uuid:id>/pin/",                ChannelPinView.as_view(),              name="chat-channel-pin"),
    path("messages/<uuid:id>/",                    MessageDetailView.as_view(),           name="chat-message-detail"),
    path("messages/<uuid:id>/replies/",            MessageRepliesView.as_view(),          name="chat-message-replies"),
    path("messages/<uuid:id>/reactions/",          MessageReactionsView.as_view(),        name="chat-message-reactions"),
    path("dms/",                                   DMOpenView.as_view(),                  name="chat-dm-open"),
    path("dms/group/",                             GroupDMOpenView.as_view(),             name="chat-dm-group-open"),
]
