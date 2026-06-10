"""
Chat factories — Channels + memberships + messages.
"""
from __future__ import annotations

import uuid

from donna.chat.models import Channel, ChannelMembership, Message


def make_channel(
    *,
    workspace,
    name: str | None = None,
    slug: str | None = None,
    kind: str = Channel.Kind.CHANNEL,
    visibility: str = Channel.Visibility.PUBLIC,
    admins: list | None = None,
    members: list | None = None,
    settings: dict | None = None,
) -> Channel:
    """Create a Channel. For DMs use ``kind=DIRECT`` and pass ``members=[user_a, user_b]``."""
    base = name or f"ch-{uuid.uuid4().hex[:6]}"
    if kind == Channel.Kind.DIRECT:
        # DMs: no name/slug, visibility forced PRIVATE by DB CHECK.
        channel = Channel.objects.create(
            workspace=workspace,
            kind=Channel.Kind.DIRECT,
            visibility=Channel.Visibility.PRIVATE,
            name="",
            slug="",
            settings=settings or {},
        )
    else:
        channel = Channel.objects.create(
            workspace=workspace,
            kind=kind,
            name=base,
            slug=slug or base,
            visibility=visibility,
            settings=settings or {},
        )

    for u in admins or []:
        ChannelMembership.objects.get_or_create(
            channel=channel, user=u,
            defaults={"role": ChannelMembership.Role.ADMIN},
        )
    for u in members or []:
        ChannelMembership.objects.get_or_create(
            channel=channel, user=u,
            defaults={"role": ChannelMembership.Role.MEMBER},
        )
    return channel


def make_message(*, channel, author, body: str = "test message") -> Message:
    return Message.objects.create(channel=channel, author_user=author, body=body)
