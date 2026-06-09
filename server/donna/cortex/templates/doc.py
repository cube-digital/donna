"""DocSpec — Drive / Notion / SharePoint / OneDrive / Dropbox docs.

``doc_type`` is REQUIRED (closed Literal, 16 values). Connectors emit
deterministic values when known; HaikuFitter fills when not.
"""
from __future__ import annotations

from donna.cortex.embeddings import head_tail_sampler
from donna.cortex.folders import FlatFolderResolver
from donna.cortex.registry import TypeSpec, register_type
from donna.cortex.schemas import DocExtensions


DocSpec = TypeSpec(
    type="doc",
    extensions_model=DocExtensions,
    fit_model=DocExtensions,  # Haiku may fill doc_type if connector can't
    template_path="doc.j2",
    nav_fields=["doc_type"],
    folder_resolver=FlatFolderResolver(bucket="docs"),
    version="doc@v1",
    embedding_sampler=head_tail_sampler,  # intro + signatures/addendums
)

register_type(DocSpec)
