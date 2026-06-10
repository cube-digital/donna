from __future__ import annotations

from django.urls import path

from donna.core.routers import SimpleRouter
from donna.workspaces.api.v1.views import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationPreviewView,
    WorkspaceMembershipViewSet,
    WorkspaceViewSet,
)

router = SimpleRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")
router.register(r"members", WorkspaceMembershipViewSet, basename="workspace-membership")

urlpatterns = [
    # Invitations — flat namespace per plans/04-roadmap.md Phase 2a.
    # The token-bearing preview + accept endpoints are public; create
    # requires X-Workspace-Id + caller is workspace admin/owner. All
    # three live under /api/v1/invitations and bypass WorkspaceMiddleware
    # (see donna.workspaces.middlewares.WorkspaceMiddleware.IGNORED_PATHS).
    path("invitations/",                       InvitationCreateView.as_view(),  name="invitation-create"),
    path("invitations/<str:token>/",           InvitationPreviewView.as_view(), name="invitation-preview"),
    path("invitations/<str:token>/accept/",    InvitationAcceptView.as_view(),  name="invitation-accept"),
    *router.urls,
]
