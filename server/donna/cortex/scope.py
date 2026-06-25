"""Scope suggestion ladder — T0 (connector hint) → T1 (deterministic alias) → T2+ (LLM, deferred).

Phase 4c (2026-06-15). Runs at write time inside the pipeline:
given a DeliveryPackage's metadata + extracted entities, suggest a
``(client_id, project_id)`` tuple if confidence is high enough to
auto-fill. Below threshold the row stays at workspace root and the
write API surfaces it for human promotion (PATCH /scope).

Ladder tiers:

- **T0 (free, deterministic)** — connector explicitly tagged the
  payload with ``client_slug`` / ``project_slug`` / explicit ids in
  ``DeliveryPackage.metadata['scope_hint']``. Trust verbatim.
- **T1 (free, deterministic)** — extracted entity domains map to a
  known ``org(relationship!=self).email_domains[]`` row → auto-assign
  ``client_id`` from that org. If exactly one ``project`` row is open
  under that client, also assign ``project_id``.
- **T2+ Haiku-contextual / T4 human** — deferred to a later phase
  (just below the threshold the row enters a ``suggested_scope``
  queue for bulk-confirm UI — Phase 5).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from donna.cortex.clustering import Scope

logger = logging.getLogger(__name__)


def scope_slugs_for(scope: "Scope") -> tuple[str | None, str | None]:
    """Resolve ``client_id`` / ``project_id`` UUIDs → folder slugs.

    Returns ``(client_prefix, project_slug)``:

    - ``client_prefix`` is **relationship-aware**: for a client org with
      ``relationship="vendor"`` and ``slug="animawings"`` you get
      ``"vendors/animawings"``. For ``relationship="client"`` you get
      ``"clients/animawings"``. ``relationship="self"`` returns ``""``
      (workspace root). This lets ``folders.temporal("emails")`` produce
      ``vendors/animawings/emails/2026/05`` without a separate lookup.
    - ``project_slug`` stays the project's slug only. Project bucket
      defaults to the parent client's bucket; rare standalone projects
      land under ``projects/<slug>/``.

    Either return may be ``None`` when the scope id is unset or the
    entity row is missing.
    """
    # Local import: avoids module-load cycle with cortex.models, which
    # transitively imports donna.workspaces (and back).
    from donna.cortex.models import CortexEntity
    from donna.cortex.folders import RELATIONSHIP_BUCKETS

    client_prefix: str | None = None
    project_slug: str | None = None

    if scope.client_id is not None:
        client = CortexEntity.objects.filter(id=scope.client_id).first()
        if client:
            ext = client.extensions or {}
            own_slug = ext.get("slug")
            relationship = ext.get("relationship", "unknown")
            if own_slug:
                if relationship == "self":
                    client_prefix = ""  # workspace root
                else:
                    bucket = RELATIONSHIP_BUCKETS.get(relationship, "unknown")
                    client_prefix = f"{bucket}/{own_slug}"

    if scope.project_id is not None:
        project = CortexEntity.objects.filter(id=scope.project_id).first()
        if project:
            project_slug = (project.extensions or {}).get("slug")

    return client_prefix, project_slug


@dataclass(frozen=True)
class ScopeSuggestion:
    client_id: UUID | None = None
    project_id: UUID | None = None
    confidence: float = 0.0
    basis: str = ""          # "t0_hint" | "t1_domain" | "t1_alias" | "none"
    auto_apply: bool = False


# Auto-apply threshold — only T0/T1 hit this. T2/T3 surface as
# suggestions for bulk-confirm.
_AUTO_APPLY = 0.85


def suggest_scope(
    *,
    workspace_id: UUID,
    metadata: dict | None,
    candidate_domains: list[str] | None = None,
) -> ScopeSuggestion:
    """Run T0 → T1 ladder. Returns the strongest suggestion.

    ``metadata`` is the DeliveryPackage's ``metadata`` dict; T0 reads
    ``scope_hint`` from it. ``candidate_domains`` is the set of email
    domains surfaced by the extractor (used by T1).
    """
    # T0 — explicit connector hint.
    t0 = _t0_explicit_hint(metadata or {}, workspace_id)
    if t0 is not None:
        return t0

    # T1 — deterministic alias match via domain → org(relationship=client).
    if candidate_domains:
        t1 = _t1_domain_match(workspace_id, candidate_domains)
        if t1 is not None:
            return t1

    return ScopeSuggestion(basis="none", confidence=0.0, auto_apply=False)


def _t0_explicit_hint(metadata: dict, workspace_id: UUID) -> ScopeSuggestion | None:
    hint = metadata.get("scope_hint")
    if not isinstance(hint, dict):
        return None
    try:
        cid = UUID(str(hint["client_id"])) if hint.get("client_id") else None
        pid = UUID(str(hint["project_id"])) if hint.get("project_id") else None
    except (TypeError, ValueError):
        return None
    if cid is None and pid is None:
        return None
    return ScopeSuggestion(
        client_id=cid,
        project_id=pid,
        confidence=0.99,
        basis="t0_hint",
        auto_apply=True,
    )


def _t1_domain_match(
    workspace_id: UUID,
    candidate_domains: list[str],
) -> ScopeSuggestion | None:
    """Match extracted domains against curated ``org`` rows.

    Picks the org whose ``email_domains[]`` contains any candidate
    domain AND whose relationship != "self" (workspace-owner doesn't
    scope its own content). If exactly one open project hangs under
    that client, auto-include the project_id.
    """
    from donna.cortex.models import CortexEntity

    domains = [d.lower() for d in candidate_domains if d]
    if not domains:
        return None

    # Find candidate orgs (any one of the domains matches an
    # email_domains[] entry). The JSONB filter ``contains`` works
    # element-wise on a list.
    org_q = CortexEntity.objects.filter(
        workspace_id=workspace_id,
        type="org",
        superseded_by__isnull=True,
    )
    matched_org: CortexEntity | None = None
    for d in domains:
        hit = org_q.filter(extensions__email_domains__contains=[d]).first()
        if hit and (hit.extensions or {}).get("relationship") != "self":
            matched_org = hit
            break

    if matched_org is None:
        return None

    client_id = matched_org.id
    project_id: UUID | None = None
    open_projects = (
        CortexEntity.objects
        .filter(
            workspace_id=workspace_id,
            type="project",
            client_id=client_id,
            superseded_by__isnull=True,
        )
        .filter(extensions__status__in=["active", "proposed"])
        .values_list("id", flat=True)
    )
    open_projects_list = list(open_projects[:2])
    if len(open_projects_list) == 1:
        project_id = open_projects_list[0]

    return ScopeSuggestion(
        client_id=client_id,
        project_id=project_id,
        confidence=0.90,
        basis="t1_domain",
        auto_apply=True,
    )
