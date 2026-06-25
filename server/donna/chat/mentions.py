"""Mention parser — general chat infrastructure.

Body conventions:
- @<handle>     → User (Message.mentions M2M)
- @donna        → mention_flags["donna"] = True
                  Triggers agent dispatch + memory persistence
                  (handled in ChatService.send_message, not here).
- @channel      → mention_flags["channel"] = True
- @everyone     → mention_flags["everyone"] = True

Handle resolution: User.handle (lowercased). Falls back to nothing — if a
handle doesn't resolve, the @<token> stays inert in the body (notification
fanout simply skips unknown handles).

Lives under ``donna.chat`` (not ``donna.chat.agents``) because mentions are
a general chat feature consumed by humans and agents alike.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from donna.chat.models import Channel
    from donna.users.models import User


# Word-boundary @handle — disallows email-prefix matching (@foo in foo@bar.com).
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_\.\-]+)")

SPECIAL = frozenset({"donna", "channel", "everyone"})


def parse(body: str, channel: "Channel") -> tuple[list["User"], dict[str, bool]]:
    """Extract mentioned users + special flags from ``body``.

    Returns:
        (users, flags) where ``users`` is a deduped list of User instances
        belonging to the channel's workspace, and ``flags`` is
        ``{"donna": bool, "channel": bool, "everyone": bool}``.
    """
    from donna.users.models import User

    raw_handles = {m.group(1).lower() for m in _MENTION_RE.finditer(body or "")}
    flags = {k: (k in raw_handles) for k in SPECIAL}
    user_handles = raw_handles - SPECIAL
    if not user_handles:
        return [], flags

    users = list(
        User.objects
        .filter(
            workspace_memberships__workspace=channel.workspace,
            handle__in=user_handles,
        )
        .distinct()
    )
    return users, flags
