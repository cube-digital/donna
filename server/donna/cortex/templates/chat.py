"""ChatSpec — Slack / WhatsApp / Discord / Telegram / Signal threads."""
from __future__ import annotations

from donna.cortex.embeddings import head_heavy_sampler
from donna.cortex.folders import ChatFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import ChatExtensions


ChatSpec = TypeSpec(
    type="chat",
    extensions_model=ChatExtensions,
    fit_model=None,
    template_path="chat.j2",
    nav_fields=["channel"],
    folder_resolver=ChatFolderResolver(),
    version="chat@v1",
    embedding_sampler=head_heavy_sampler,  # recency dominates chats
)

register_type(ChatSpec)
