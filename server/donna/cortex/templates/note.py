"""NoteSpec — manual notes via MCP / UI.

``note_type`` is REQUIRED (5-value Literal): brainstorm / checkpoint /
journal / action_item / open_question.
"""
from __future__ import annotations

from donna.cortex.folders import FlatFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import NoteExtensions


NoteSpec = TypeSpec(
    type="note",
    extensions_model=NoteExtensions,
    fit_model=NoteExtensions,
    template_path="note.j2",
    nav_fields=["note_type"],
    folder_resolver=FlatFolderResolver(bucket="notes"),
    version="note@v1",
)

register_type(NoteSpec)
