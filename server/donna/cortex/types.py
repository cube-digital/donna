"""Declarative TypeSpec table — single source for all 12 entity types.

Replaces the 12 ``templates/<type>.py`` modules + the apps.ready()
discovery walk (refactor 2026-06-14). One import side-effect: every
TypeSpec is registered in ``donna.cortex.registry`` at module load.

The ``.j2`` templates stay where they are (``templates/<type>.j2``)
and load via the normal Jinja FileSystemLoader.
"""
from __future__ import annotations

from donna.cortex import folders, schemas
from donna.cortex.embeddings import (
    fixed_window_sampler,
    head_heavy_sampler,
    head_tail_sampler,
    uniform_sampler,
)
from donna.cortex.registry import TypeSpec, register_type


SPECS: tuple[TypeSpec, ...] = (
    TypeSpec(
        type="meeting",
        extensions_model=schemas.MeetingExtensions,
        fit_model=None,
        template_path="meeting.j2",
        nav_fields=["attendees"],
        folder_resolver=folders.temporal("meetings"),
        version="meeting@v1",
        embedding_sampler=uniform_sampler,
    ),
    TypeSpec(
        type="email",
        extensions_model=schemas.EmailExtensions,
        fit_model=None,
        template_path="email.j2",
        nav_fields=["thread_id"],
        folder_resolver=folders.temporal("emails"),
        version="email@v1",
        embedding_sampler=head_heavy_sampler,
    ),
    TypeSpec(
        type="chat",
        extensions_model=schemas.ChatExtensions,
        fit_model=None,
        template_path="chat.j2",
        nav_fields=["channel"],
        folder_resolver=folders.chat,
        version="chat@v1",
        embedding_sampler=head_heavy_sampler,
    ),
    TypeSpec(
        type="doc",
        extensions_model=schemas.DocExtensions,
        fit_model=schemas.DocExtensions,
        template_path="doc.j2",
        nav_fields=["doc_type"],
        folder_resolver=folders.flat("docs"),
        version="doc@v1",
        embedding_sampler=head_tail_sampler,
    ),
    TypeSpec(
        type="ticket",
        extensions_model=schemas.TicketExtensions,
        fit_model=None,
        template_path="ticket.j2",
        nav_fields=["provider", "external_id", "status"],
        folder_resolver=folders.ticket,
        version="ticket@v1",
        embedding_sampler=head_heavy_sampler,
    ),
    TypeSpec(
        type="clip",
        extensions_model=schemas.ClipExtensions,
        fit_model=None,
        template_path="clip.j2",
        nav_fields=["url", "why_captured"],
        folder_resolver=folders.flat("clips"),
        version="clip@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="note",
        extensions_model=schemas.NoteExtensions,
        fit_model=schemas.NoteExtensions,
        template_path="note.j2",
        nav_fields=["note_type"],
        folder_resolver=folders.flat("notes"),
        version="note@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="person",
        extensions_model=schemas.PersonExtensions,
        fit_model=None,
        template_path="person.j2",
        nav_fields=[],
        folder_resolver=folders.person,
        version="person@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="org",
        extensions_model=schemas.OrgExtensions,
        fit_model=None,
        template_path="org.j2",
        nav_fields=["relationship"],
        folder_resolver=folders.org,
        version="org@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="project",
        extensions_model=schemas.ProjectExtensions,
        fit_model=None,
        template_path="project.j2",
        nav_fields=["status"],
        folder_resolver=folders.project,
        version="project@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="concept",
        extensions_model=schemas.ConceptExtensions,
        fit_model=None,
        template_path="concept.j2",
        nav_fields=["maturity"],
        folder_resolver=folders.concept,
        version="concept@v1",
        embedding_sampler=fixed_window_sampler,
    ),
    TypeSpec(
        type="decision",
        extensions_model=schemas.DecisionExtensions,
        fit_model=None,
        template_path="decision.j2",
        nav_fields=["adr_status"],
        folder_resolver=folders.decision,
        version="decision@v1",
        embedding_sampler=head_tail_sampler,
    ),
)


for _spec in SPECS:
    register_type(_spec)
