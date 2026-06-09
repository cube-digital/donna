"""TicketSpec — Jira / Linear / GitHub Issues / Asana / ClickUp."""
from __future__ import annotations

from donna.cortex.embeddings import head_heavy_sampler
from donna.cortex.folders import TicketFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import TicketExtensions


TicketSpec = TypeSpec(
    type="ticket",
    extensions_model=TicketExtensions,
    fit_model=None,
    template_path="ticket.j2",
    nav_fields=["provider", "external_id", "status"],
    folder_resolver=TicketFolderResolver(),
    version="ticket@v1",
    embedding_sampler=head_heavy_sampler,  # issue summary at top, resolution at end
)

register_type(TicketSpec)
