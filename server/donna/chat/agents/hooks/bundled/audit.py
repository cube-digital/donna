"""Plan 13 §2.3 — built-in audit hook.

Logs every tool call to structlog with workspace + session + channel +
tool name + a short hash of the args/result so the audit trail is
queryable without leaking raw payloads. Used as the canonical example of
a workspace-global compliance hook.
"""
from __future__ import annotations

import hashlib
import json

from donna.chat.agents.hooks import HookContext, HookResult, register
from donna.core.logging import get_logger

logger = get_logger(__name__)


def _hash(d: dict | None) -> str:
    if d is None:
        return ""
    blob = json.dumps(d, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def audit_pre(ctx: HookContext) -> HookResult:
    logger.info(
        "tool.start",
        tool=ctx.tool_name,
        args_hash=_hash(ctx.tool_args),
        workspace_id=str(getattr(ctx.workspace, "id", "")),
        session_id=ctx.session_id,
        channel_id=ctx.channel_id,
    )
    return HookResult()


def audit_post(ctx: HookContext) -> HookResult:
    logger.info(
        "tool.end",
        tool=ctx.tool_name,
        result_hash=_hash(ctx.tool_result),
        workspace_id=str(getattr(ctx.workspace, "id", "")),
        session_id=ctx.session_id,
        channel_id=ctx.channel_id,
    )
    return HookResult()


register("pre_tool_use", audit_pre)
register("post_tool_use", audit_post)
