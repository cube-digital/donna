"""MeetingSpec — Fathom / Zoom / Meet / Teams meeting entities."""
from __future__ import annotations

from donna.cortex.embeddings import uniform_sampler
from donna.cortex.folders import TemporalFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import MeetingExtensions


MeetingSpec = TypeSpec(
    type="meeting",
    extensions_model=MeetingExtensions,
    fit_model=None,  # provider metadata satisfies all nav fields
    template_path="meeting.j2",
    nav_fields=["attendees"],
    folder_resolver=TemporalFolderResolver(bucket="meetings"),
    version="meeting@v1",
    embedding_sampler=uniform_sampler,  # decisions distributed across the transcript
)

register_type(MeetingSpec)
