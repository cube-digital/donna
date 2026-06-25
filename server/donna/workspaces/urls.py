from __future__ import annotations

from donna.core.routers import SimpleRouter
from donna.workspaces.api.v1.views import (
    PublicInvitationViewSet,
    WorkspaceInvitationViewSet,
    WorkspaceMembershipViewSet,
    WorkspaceViewSet,
)

router = SimpleRouter()
# Register the more-specific path BEFORE the generic `workspaces` route so
# the router matches `/workspaces/invitations/` instead of treating
# "invitations" as a `<pk>` on `WorkspaceViewSet`.
router.register(
    r"workspaces/invitations",
    WorkspaceInvitationViewSet,
    basename="workspace-invitation",
)
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")
router.register(r"members", WorkspaceMembershipViewSet, basename="workspace-membership")

# Public token-based endpoints — bypasses workspace tenancy via
# IGNORED_PATHS in settings.
public_router = SimpleRouter()
public_router.register(
    r"invitations",
    PublicInvitationViewSet,
    basename="public-invitation",
)

urlpatterns = router.urls
public_urlpatterns = public_router.urls
