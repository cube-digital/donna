"""
Django middleware for structured logging and multi-tenant context.

Provides:
- Request context propagation for all logs within a request lifecycle.
- Tenant resolution from ``X-Tenant-Id`` header or user membership.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404

from donna.core.context import set_tenant_context
from donna.core.logging import get_logger, update_request_context
from donna.workspaces.models import Workspace

logger = get_logger(__name__)



class UserContextMiddleware:
    """
    Middleware to add authenticated user info to logging context.

    Must run AFTER AuthenticationMiddleware to have access to request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Add user context if authenticated
        if hasattr(request, "user") and request.user.is_authenticated:
            update_request_context(
                user_id=str(request.user.id),
                user_email=getattr(request.user, "email", None),
            )

        return self.get_response(request)


class WorkspaceMiddleware:
    """
    Resolve the active tenant for every request.

    Resolution order:
        1. ``X-Tenant-Id`` header  -- resolved immediately.
        2. Authenticated user's first company membership -- resolved
           lazily via ``SimpleLazyObject`` so that DRF token/JWT
           authentication (which runs inside the view layer, *after*
           middleware) has already set ``request.user`` by the time
           ``request.company`` is first accessed.

    On success the middleware sets:
        * ``request.company``   -- :class:`Company` instance (or lazy proxy)
        * ``request.tenant_id`` -- ``str(company.id)``

    Must run **after** ``AuthenticationMiddleware``.
    """

    TENANT_NOT_FOUND_EXCEPTION = Http404

    # Paths (prefix match) that do **not** require a tenant header.
    IGNORED_PATHS = {
        "/admin": ["GET", "POST", "PATCH", "PUT", "DELETE"],
        "/swagger": ["GET", "POST", "PATCH", "PUT", "DELETE"],
        "/api/auth": ["POST", "GET"],
        "/api/health": ["GET"],
        # Current-user profile — identity-scoped, not workspace-scoped.
        "/api/v1/users/me": ["GET", "PATCH", "POST", "DELETE"],
        "/api/v1/workspaces": ["POST", "GET"],
        # Public token-based invitation endpoints — no tenant context.
        "/api/v1/invitations": ["GET", "POST"],
        "/favicon.ico": ["GET"],
        # Frontend SPA routes — OAuth callbacks 302 to /app/... for UI feedback;
        # workspace context comes from the SPA session, not the URL.
        "/app": ["GET"],
        # SSE stream fans in across all user's workspaces — no single
        # workspace context applies. See plans/10-realtime-layer.md.
        "/api/v1/notifications/stream": ["GET"],
        # WebSocket handshake (HTTP upgrade) — workspace context lives
        # in per-subscribe authorization, not on the connection itself.
        "/ws": ["GET"],
    }

    # Paths (suffix match) that do **not** require a tenant header. Used for
    # integration callbacks: provider webhooks and OAuth redirect targets,
    # which both terminate at predictable URL suffixes regardless of the
    # connector slug in the middle.
    IGNORED_SUFFIXES = {
        "/webhook/callback": ["POST"],
        "/oauth/callback":   ["GET"],
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self.process_request(request)

        try:
            response = self.get_response(request)
        except Exception as exc:
            self.process_exception(request, exc)
            raise

        return self.process_response(request, response)

    # Named sub-routes nested under an otherwise context-free ignored prefix
    # that DO operate inside the active workspace and so require the header.
    # "/api/v1/workspaces" is ignored (create/list needs no active workspace),
    # but its `startswith` match also catches "/api/v1/workspaces/invitations/",
    # which is tenanted — don't let the broad prefix strip its context.
    TENANTED_UNDER_IGNORED = ("/api/v1/workspaces/invitations",)

    def process_request(self, request):
        # Non-API requests carry no tenant context: the SPA shell (index.html),
        # its hashed static assets, and deep-link refreshes (e.g. GET /cortex)
        # are plain document/asset loads. Only the /api/ surface is tenanted —
        # the SPA supplies X-Workspace-Id on its API calls. Gating document
        # loads here would 403 every SPA deep link. (admin/swagger/ws are also
        # non-API and were already exempt via IGNORED_PATHS.)
        if not request.path.startswith("/api/"):
            request.workspace = None
            request.company = None
            request.tenant_id = None
            return None

        tenanted_override = any(
            request.path.startswith(p) for p in self.TENANTED_UNDER_IGNORED
        )
        if not tenanted_override:
            for path, methods in self.IGNORED_PATHS.items():
                if request.path.startswith(path) and request.method in methods:
                    request.workspace = None
                    request.company = None
                    request.tenant_id = None
                    return None

            for suffix, methods in self.IGNORED_SUFFIXES.items():
                if request.path.endswith(suffix) and request.method in methods:
                    request.workspace = None
                    request.company = None
                    request.tenant_id = None
                    return None

        # Tenanted path — X-Workspace-Id header is mandatory. Resolve once,
        # attach to request, propagate to logging contextvars. Views can then
        # trust request.workspace is always set (or this middleware short-
        # circuits before the view runs).
        workspace_id = request.META.get("HTTP_X_WORKSPACE_ID")
        if not workspace_id:
            raise PermissionDenied("X-Workspace-Id header required")

        try:
            workspace = Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist:
            raise self.TENANT_NOT_FOUND_EXCEPTION(
                f"No workspace found for id {workspace_id}"
            )

        request.workspace = workspace
        request.company = workspace
        set_tenant_context(request)
        return None

    def process_response(self, request, response):
        set_tenant_context(None)
        return response

    def process_exception(self, request, exception):
        set_tenant_context(None)
