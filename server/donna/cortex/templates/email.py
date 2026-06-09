"""EmailSpec — Gmail / Outlook / IMAP thread entities."""
from __future__ import annotations

from donna.cortex.embeddings import head_heavy_sampler
from donna.cortex.folders import TemporalFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import EmailExtensions


EmailSpec = TypeSpec(
    type="email",
    extensions_model=EmailExtensions,
    fit_model=None,
    template_path="email.j2",
    nav_fields=["thread_id"],
    folder_resolver=TemporalFolderResolver(bucket="emails"),
    version="email@v1",
    embedding_sampler=head_heavy_sampler,  # latest reply usually at top
)

register_type(EmailSpec)
