"""Cortex MCP server — Model Context Protocol surface.

Exposes four tools over stdio (Claude Code's default transport) +
optional HTTP/SSE:

- ``cortex_query``    — hybrid search (RRF dense + tsvector + keyword)
- ``cortex_read``     — full entity body + edges by id
- ``cortex_context``  — depth-bounded neighbor walk
- ``cortex_create``   — linter-gated entity write

Workspace selection: the MCP client sets ``workspace_id`` in the tool
arguments (env-var fallback ``DONNA_MCP_WORKSPACE_ID`` for one-shot
client setups). User context defaults to None — the call runs as
"donna" author for create_entity unless overridden.

Install the official SDK once before running:  ``uv add 'mcp[cli]'``
Start the stdio server:                          ``manage.py cortex_mcp``
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID


logger = logging.getLogger(__name__)


def _resolve_workspace(workspace_id: str | None):
    """Resolve the workspace by id (arg or env fallback)."""
    from donna.workspaces.models import Workspace

    ws_id = workspace_id or os.environ.get("DONNA_MCP_WORKSPACE_ID")
    if not ws_id:
        raise ValueError(
            "workspace_id is required (pass as tool arg or set "
            "DONNA_MCP_WORKSPACE_ID)."
        )
    return Workspace.objects.get(id=ws_id)


def _svc(workspace_id: str | None):
    from donna.cortex.services import CortexService
    return CortexService(current_user=None, company=_resolve_workspace(workspace_id))


# ── Tool implementations (transport-independent) ────────────────────


def tool_cortex_query(args: dict[str, Any]) -> dict:
    """Run a hybrid cortex query."""
    workspace_id = args.pop("workspace_id", None)
    text = args.pop("text")
    hits = _svc(workspace_id).query(text=text, **args)
    return {"results": [h.summary() for h in hits]}


def tool_cortex_read(args: dict[str, Any]) -> dict:
    workspace_id = args.get("workspace_id")
    entity_id = UUID(str(args["entity_id"]))
    include_body = bool(args.get("include_body", True))
    card = _svc(workspace_id).read_entity(entity_id, include_body=include_body)
    if card is None:
        return {"error": "entity_not_found", "id": str(entity_id)}
    return card.as_dict()


def tool_cortex_context(args: dict[str, Any]) -> dict:
    workspace_id = args.get("workspace_id")
    entity_id = UUID(str(args["entity_id"]))
    depth = int(args.get("depth", 1))
    cards = _svc(workspace_id).get_context(entity_id, depth=depth)
    return {"neighbors": [c.as_dict() for c in cards]}


def tool_cortex_create(args: dict[str, Any]) -> dict:
    workspace_id = args.pop("workspace_id", None)
    entity = _svc(workspace_id).create_entity(**args)
    return {"id": str(entity.id), "type": entity.type, "title": entity.title}


# ── MCP server wiring (official mcp SDK) ────────────────────────────


def build_server():
    """Construct an MCP ``Server`` with all four cortex tools registered.

    Returns the bound server instance. Raises ImportError if the mcp
    SDK isn't installed — connect transport in caller.
    """
    try:
        from mcp.server import Server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the 'mcp' SDK. Install with: "
            "uv add 'mcp[cli]'"
        ) from exc

    server = Server("donna-cortex")

    tools_def = [
        Tool(
            name="cortex_query",
            description=(
                "Hybrid search over the cortex silver layer "
                "(meetings/emails/docs/tickets/people/decisions). "
                "Metadata filters apply BEFORE similarity. Returns "
                "ranked entity headers with source URIs."
            ),
            inputSchema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text":        {"type": "string"},
                    "type":        {"type": "string"},
                    "doc_type":    {"type": "string"},
                    "client_id":   {"type": "string", "format": "uuid"},
                    "project_id":  {"type": "string", "format": "uuid"},
                    "limit":       {"type": "integer", "default": 8, "maximum": 25},
                    "workspace_id":{"type": "string", "format": "uuid"},
                },
            },
        ),
        Tool(
            name="cortex_read",
            description="Read a single cortex entity (body + edges) by id.",
            inputSchema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id":    {"type": "string", "format": "uuid"},
                    "include_body": {"type": "boolean", "default": True},
                    "workspace_id": {"type": "string", "format": "uuid"},
                },
            },
        ),
        Tool(
            name="cortex_context",
            description="Walk neighbors via entity_refs + sources (depth 1 or 2).",
            inputSchema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id":    {"type": "string", "format": "uuid"},
                    "depth":        {"type": "integer", "default": 1, "maximum": 2},
                    "workspace_id": {"type": "string", "format": "uuid"},
                },
            },
        ),
        Tool(
            name="cortex_create",
            description=(
                "Create a cortex entity (linter-gated, atomic). body_md "
                "must end with 'Source: <uri>' or 'Spawned by: <id>'."
            ),
            inputSchema={
                "type": "object",
                "required": ["type", "author", "source", "title", "body_md"],
                "properties": {
                    "type":    {"type": "string"},
                    "author":  {"type": "string", "enum": ["donna", "human", "agent"]},
                    "source":  {"type": "string"},
                    "title":   {"type": "string"},
                    "body_md": {"type": "string"},
                    "extensions":         {"type": "object"},
                    "occurred_at":        {"type": "string", "format": "date-time"},
                    "client_id":          {"type": "string", "format": "uuid"},
                    "project_id":         {"type": "string", "format": "uuid"},
                    "bronze_storage_key": {"type": "string"},
                    "workspace_id":       {"type": "string", "format": "uuid"},
                },
            },
        ),
    ]

    _dispatch = {
        "cortex_query":   tool_cortex_query,
        "cortex_read":    tool_cortex_read,
        "cortex_context": tool_cortex_context,
        "cortex_create":  tool_cortex_create,
    }

    @server.list_tools()
    async def _list_tools():
        return tools_def

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None):
        fn = _dispatch.get(name)
        if fn is None:
            payload = {"error": "unknown_tool", "name": name}
        else:
            try:
                payload = fn(dict(arguments or {}))
            except Exception as exc:  # noqa: BLE001
                logger.exception("cortex_mcp_tool_error", extra={"tool": name})
                payload = {"error": "tool_run_failed", "tool": name, "detail": str(exc)}
        return [TextContent(type="text", text=json.dumps(payload, default=str))]

    return server


def run_stdio() -> None:
    """Run the MCP server over stdio — Claude Code's default transport."""
    import asyncio

    from mcp.server.stdio import stdio_server

    async def _main():
        server = build_server()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_main())
