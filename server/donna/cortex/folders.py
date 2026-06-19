"""Folder resolvers — Universal Folder Structure (spec §9, Variant 1).

Each entity has ONE canonical filesystem location (topical or temporal
lens). Cross-axis projections (entity-axis derived view, ``_index.md``)
are query-time only, computed by ``CortexService`` rather than carried
here.

Path layout depends on ``client_id`` / ``project_id`` scope:

- Workspace-owner content  (no client, no project)  → ``<bucket>/...``
- Workspace-internal project (no client, project)   → ``projects/<project-slug>/<bucket>/...``
- Client root              (client, no project)     → ``clients/<client-slug>/<bucket>/...``
- Client project           (client + project)       → ``clients/<client-slug>/projects/<project-slug>/<bucket>/...``

Each resolver is a **plain function** (refactored 2026-06-14 from
9 single-method classes — same behavior, less ceremony). Functions
that need configuration return a closure (``temporal("meetings")``).
``TypeSpec.folder_resolver`` is a ``FolderFn`` — a callable matching
the protocol below.

Type buckets:

| type        | bucket           | sub-pattern                |
|-------------|------------------|-----------------------------|
| meeting     | ``meetings/``    | ``YYYY/MM/<date>-<slug>.md``|
| email       | ``emails/``      | ``YYYY/MM/<date>-<slug>.md``|
| chat        | ``chats/``       | ``<channel>/YYYY-MM-DD.md`` |
| doc         | ``docs/``        | ``<date>-<slug>.md``        |
| ticket      | ``tickets/``     | ``<provider>/<external-id>.md`` |
| clip        | ``clips/``       | ``<date>-<slug>.md``        |
| note        | ``notes/``       | ``<date>-<slug>.md``        |
| project     | (n/a)            | ``project.md`` at project root |
| person      | ``people/``      | ``<slug>.md`` at workspace root |
| org         | (special)        | ``org.md`` at workspace OR client root |
| concept     | ``concepts/``    | ``<slug>.md`` at workspace root |
| decision    | ``decisions/``   | ``ADR-{W}NNNN-<slug>.md``   |
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Protocol


# A FolderFn takes type + occurred_at + extensions + scope slugs and
# returns the canonical parent path for an entity of that shape.
class FolderFn(Protocol):
    def __call__(
        self,
        *,
        type: str,
        occurred_at: datetime | str | None,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str: ...


def _scope_prefix(client_slug: str | None, project_slug: str | None) -> str:
    if client_slug and project_slug:
        return f"clients/{client_slug}/projects/{project_slug}"
    if client_slug:
        return f"clients/{client_slug}"
    if project_slug:
        return f"projects/{project_slug}"
    return ""


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p).strip("/")


def _year_month(occurred_at: datetime | str | date) -> tuple[str, str]:
    if isinstance(occurred_at, str):
        return occurred_at[:4], occurred_at[5:7]
    return f"{occurred_at.year:04d}", f"{occurred_at.month:02d}"


# ── Folder resolver functions ──────────────────────────────────────


def temporal(bucket: str) -> FolderFn:
    """``<scope>/<bucket>/YYYY/MM`` — for event-shaped types (meeting/email)."""
    def resolve(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        if occurred_at is None:
            return _join(scope, bucket, "unknown")
        year, month = _year_month(occurred_at)
        return _join(scope, bucket, year, month)
    return resolve


def flat(bucket: str) -> FolderFn:
    """``<scope>/<bucket>`` — flat, no sub-partitioning (docs / clips / notes)."""
    def resolve(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
        return _join(_scope_prefix(client_slug, project_slug), bucket)
    return resolve


def chat(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """``<scope>/chats/<channel>`` — channel-keyed (not date-keyed)."""
    scope = _scope_prefix(client_slug, project_slug)
    channel = (extensions or {}).get("channel") or "general"
    return _join(scope, "chats", channel)


def ticket(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """``<scope>/tickets/<provider>`` — provider-keyed."""
    scope = _scope_prefix(client_slug, project_slug)
    provider = (extensions or {}).get("provider") or "unknown"
    return _join(scope, "tickets", provider)


def person(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """Workspace-root ``people/`` — cross-client (spec §6 exception)."""
    return "people"


def concept(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """Workspace-root ``concepts/`` — cross-project (spec §6 exception)."""
    return "concepts"


def org(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """One ``org.md`` per scope.

    - ``relationship=self`` → workspace root → ``""``
    - any other relationship → under ``clients/<slug>``
    - spawned org without a client slug → ``clients/`` parking lot
    """
    relationship = (extensions or {}).get("relationship")
    if relationship == "self":
        return ""
    if client_slug:
        return f"clients/{client_slug}"
    return "clients"


def project(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """``project.md`` lives at the project root (no sub-bucket)."""
    return _scope_prefix(client_slug, project_slug)


def decision(*, type, occurred_at, extensions, client_slug, project_slug) -> str:
    """``<scope>/decisions/`` — ADR-NNNN ids handle uniqueness.

    Workspace-internal decisions (client_slug is None) get an ADR-W
    prefix at the slug layer (spec §9.0.1).
    """
    return _join(_scope_prefix(client_slug, project_slug), "decisions")


# Backwards-compatible Callable typing — pipelines can declare
# ``folder_resolver: FolderFn`` or simply ``Callable[..., str]``.
__all__ = [
    "FolderFn",
    "chat",
    "concept",
    "decision",
    "flat",
    "org",
    "person",
    "project",
    "temporal",
    "ticket",
]


if __name__ == "__main__":
    # Run: `python -m donna.cortex.folders` (from `server/`)
    # Pure-Python — no DB. Exercises every resolver across the four scope combos.
    from datetime import datetime as _dt, timezone

    occurred = _dt(2026, 6, 14, 14, 30, tzinfo=timezone.utc)
    SCOPES = [
        ("workspace-root", None, None),
        ("workspace-internal-project", None, "phoenix"),
        ("client-root", "acme", None),
        ("client-project", "acme", "phoenix"),
    ]

    def run(label: str, fn: FolderFn, **kw) -> None:
        print(f"\n── {label} ──")
        for scope_name, c, p in SCOPES:
            path = fn(client_slug=c, project_slug=p, **kw)
            print(f"  {scope_name:<28} → {path!r}")

    common = dict(type="meeting", occurred_at=occurred, extensions={})
    run("temporal('meetings')", temporal("meetings"), **common)
    run("temporal('emails') — no occurred_at",
        temporal("emails"), **{**common, "occurred_at": None})
    run("chat (extensions.channel='eng')",
        chat, type="chat", occurred_at=occurred, extensions={"channel": "eng"})
    run("ticket (extensions.provider='linear')",
        ticket, type="ticket", occurred_at=None, extensions={"provider": "linear"})
    run("flat('docs')", flat("docs"), **common)
    run("person", person, **common)
    run("concept", concept, **common)
    run("org — relationship=self", org,
        type="org", occurred_at=None, extensions={"relationship": "self"})
    run("org — relationship=client", org,
        type="org", occurred_at=None, extensions={"relationship": "client"})
    run("project", project,
        type="project", occurred_at=None, extensions={})
    run("decision", decision,
        type="decision", occurred_at=None, extensions={})
