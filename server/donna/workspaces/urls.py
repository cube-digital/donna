from __future__ import annotations

from donna.core.routers import SimpleRouter
from donna.workspaces.api.v1.views import (
    WorkspaceMembershipViewSet,
    WorkspaceViewSet,
)

router = SimpleRouter()
router.register(r"workspaces", WorkspaceViewSet, basename="workspace")
router.register(r"members", WorkspaceMembershipViewSet, basename="workspace-membership")

urlpatterns = router.urls
