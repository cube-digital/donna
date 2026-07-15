"""
Chat HTTP REST routes — mounted under ``/api/v1/chat/`` by
``donna/urls.py``.

WS routes live in ``donna/chat/routing.py`` and are mounted by
``donna/asgi.py``.
"""
from __future__ import annotations

from django.urls import path

from .api.v1.views import (
    ChannelAgentInstallView,
    ChannelAgentUninstallView,
    ChannelDetailView,
    ChannelArtifactDetailView,
    ChannelArtifactsView,
    ChannelListCreateView,
    ChannelMemberRemoveView,
    ChannelMembersView,
    ChannelMessageListCreateView,
    MentionCandidatesView,
    ChannelPinView,
    ChannelReadStateView,
    AgentDMOpenView,
    DMOpenView,
    GroupDMOpenView,
    MessageAnswerView,
    MessageDetailView,
    MessageReactionsView,
    MessageRepliesView,
    WorkspaceArtifactDetailView,
)


urlpatterns = [
    path("channels/",                              ChannelListCreateView.as_view(),       name="chat-channel-list"),
    path("channels/<uuid:id>/",                    ChannelDetailView.as_view(),           name="chat-channel-detail"),
    path("channels/<uuid:id>/messages/",           ChannelMessageListCreateView.as_view(),name="chat-channel-messages"),
    path("channels/<uuid:id>/members/",            ChannelMembersView.as_view(),          name="chat-channel-members"),
    path("channels/<uuid:id>/mention-candidates/", MentionCandidatesView.as_view(),       name="chat-channel-mention-candidates"),
    path("channels/<uuid:id>/members/<uuid:user_id>/", ChannelMemberRemoveView.as_view(), name="chat-channel-member-remove"),
    path("channels/<uuid:id>/read-state/",         ChannelReadStateView.as_view(),        name="chat-channel-read-state"),
    path("channels/<uuid:id>/artifacts/",          ChannelArtifactsView.as_view(),        name="chat-channel-artifacts"),
    path("channels/<uuid:id>/artifacts/<uuid:artifact_id>/", ChannelArtifactDetailView.as_view(), name="chat-channel-artifact-detail"),
    path("channels/<uuid:id>/agents/install/", ChannelAgentInstallView.as_view(), name="chat-channel-agent-install"),
    path("channels/<uuid:id>/agents/<slug:handle>/", ChannelAgentUninstallView.as_view(), name="chat-channel-agent-uninstall"),
    path("channels/<uuid:id>/pin/",                ChannelPinView.as_view(),              name="chat-channel-pin"),
    path("messages/<uuid:id>/",                    MessageDetailView.as_view(),           name="chat-message-detail"),
    path("messages/<uuid:id>/replies/",            MessageRepliesView.as_view(),          name="chat-message-replies"),
    path("messages/<uuid:id>/reactions/",          MessageReactionsView.as_view(),        name="chat-message-reactions"),
    path("messages/<uuid:id>/answer/",             MessageAnswerView.as_view(),           name="chat-message-answer"),
    path("artifacts/<uuid:artifact_id>/",          WorkspaceArtifactDetailView.as_view(),  name="chat-workspace-artifact-detail"),
    path("dms/",                                   DMOpenView.as_view(),                  name="chat-dm-open"),
    path("dms/agent/",                             AgentDMOpenView.as_view(),             name="chat-dm-agent-open"),
    path("dms/group/",                             GroupDMOpenView.as_view(),             name="chat-dm-group-open"),
]
