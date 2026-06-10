"""
Workspace + membership factories.
"""
from __future__ import annotations

import uuid

from donna.workspaces.models import Workspace, WorkspaceMembership


def make_workspace(
    *,
    name: str | None = None,
    owner=None,
    members: list[tuple] | None = None,
) -> Workspace:
    """
    Create a Workspace.

    ``owner`` (optional) is given the OWNER role.
    ``members`` is a list of ``(user, role)`` tuples for extra memberships.
    """
    if name is None:
        name = f"WS-{uuid.uuid4().hex[:8]}"
    slug = name.lower().replace(" ", "-")
    workspace = Workspace.objects.create(name=name, slug=slug)
    if owner is not None:
        WorkspaceMembership.objects.create(
            workspace=workspace, user=owner,
            role=WorkspaceMembership.Role.OWNER,
        )
    for user, role in (members or []):
        WorkspaceMembership.objects.create(
            workspace=workspace, user=user, role=role
        )
    return workspace


def add_member(workspace, user, role=WorkspaceMembership.Role.MEMBER) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=role
    )
