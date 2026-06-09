"""
Folder resolvers — Universal Folder Structure (spec §9, Variant 1).

Each entity has ONE canonical filesystem location (topical or temporal
lens). Cross-axis projections (entity-axis derived view, ``_index.md``)
are query-time only.

Path layout depends on `client_id` / `project_id` scope:

- Workspace-owner content (``client_id == None``):
  ``<type-bucket>/...`` at workspace root
- Workspace-internal project (``client_id == None, project_id != None``):
  ``projects/<project-slug>/<type-bucket>/...``
- Client root context (``client_id != None, project_id == None``):
  ``clients/<client-slug>/<type-bucket>/...``
- Client project (``client_id != None, project_id != None``):
  ``clients/<client-slug>/projects/<project-slug>/<type-bucket>/...``

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
| project     | (n/a)            | ``project.md`` at the project root |
| person      | ``people/``      | ``<slug>.md`` at workspace root |
| org         | (special)        | ``org.md`` at workspace OR client root |
| concept     | ``concepts/``    | ``<slug>.md`` at workspace root |
| decision    | ``decisions/``   | ``ADR-{W}NNNN-<slug>.md``   |

People / concepts / curated rows are cross-scope at workspace root
(spec §6 exceptions). Workspace ADR ids carry ``W`` prefix (§9.0.1).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from uuid import UUID


class FolderResolver(Protocol):
    """Compute the canonical parent path for an entity."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at: datetime | str | None,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str: ...


def _scope_prefix(client_slug: str | None, project_slug: str | None) -> str:
    """Return the path prefix that encodes the scope tuple.

    - workspace-owner (no client, no project)         → ``""``
    - workspace internal project (no client, project) → ``projects/<slug>``
    - client root (client, no project)                → ``clients/<slug>``
    - client project (client + project)               → ``clients/<slug>/projects/<slug>``
    """
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


# ── Type-specific resolvers ────────────────────────────────────────


class TemporalFolderResolver:
    """``<scope>/<bucket>/YYYY/MM`` — for event-shaped types (meeting/email)."""

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        if occurred_at is None:
            return _join(scope, self._bucket, "unknown")
        year, month = _year_month(occurred_at)
        return _join(scope, self._bucket, year, month)


class ChatFolderResolver:
    """``<scope>/chats/<channel>`` — channel-keyed (not date-keyed)."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        channel = (extensions or {}).get("channel") or "general"
        return _join(scope, "chats", channel)


class TicketFolderResolver:
    """``<scope>/tickets/<provider>`` — provider-keyed."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        provider = (extensions or {}).get("provider") or "unknown"
        return _join(scope, "tickets", provider)


class FlatFolderResolver:
    """``<scope>/<bucket>`` — flat, no sub-partitioning (docs / clips / notes)."""

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        return _join(scope, self._bucket)


class PersonFolderResolver:
    """Workspace-root ``people/<slug>`` — cross-client (spec §6 exception)."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        return "people"


class ConceptFolderResolver:
    """Workspace-root ``concepts/<slug>`` — cross-project (spec §6 exception)."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        return "concepts"


class OrgFolderResolver:
    """One ``org.md`` per scope.

    - ``relationship: self`` → workspace root → ``""``
    - any other relationship → under ``clients/<slug>``
    """

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        relationship = (extensions or {}).get("relationship")
        if relationship == "self":
            return ""
        if client_slug:
            return f"clients/{client_slug}"
        # Spawned org without client_slug — park in workspace root for
        # later promotion via Path 1 strict.
        return "clients"


class ProjectFolderResolver:
    """``project.md`` lives at the project root (no sub-bucket)."""

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        return _scope_prefix(client_slug, project_slug)


class DecisionFolderResolver:
    """``<scope>/decisions/`` — same bucket; ADR-NNNN ids handle uniqueness.

    Workspace-internal decisions (client_slug is None) get ``ADR-W``
    prefix at the slug layer — see spec §9.0.1.
    """

    def canonical_path(
        self,
        *,
        type: str,
        occurred_at,
        extensions: dict,
        client_slug: str | None,
        project_slug: str | None,
    ) -> str:
        scope = _scope_prefix(client_slug, project_slug)
        return _join(scope, "decisions")


# ── Derived view (entity-axis lens) ────────────────────────────────


class DerivedNamespaceView:
    """Query-time projection over the entity-axis.

    No canonical filing — source of truth is the ``entity_refs[]``
    edge on every entity that mentions the target.
    """

    def __init__(self, repository=None) -> None:
        if repository is None:
            from donna.cortex.repository import CortexEntityRepository

            repository = CortexEntityRepository()
        self._repo = repository

    def list_entity_namespace(
        self, entity_id: UUID, workspace_id: UUID
    ) -> list:
        return self._repo.find_referencing(entity_id, workspace_id)
