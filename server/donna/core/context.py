"""
Thread-local tenant context for multi-tenant isolation.

Stores the current request (and its tenant info) in a thread-local variable
so that lower layers (storage, services, managers) can access the active
tenant without requiring explicit arguments.

Usage:
    # In middleware (set on request entry):
    set_tenant_context(request)

    # In any downstream code:
    ctx = get_tenant_context()
    if ctx and hasattr(ctx, 'company'):
        tenant_id = str(ctx.company.id)
"""

import threading
import typing

from rest_framework.request import Request

_context = threading.local()


def set_tenant_context(request: typing.Optional[Request]) -> None:
	"""
	Set local context variables for the isolated tenant in
	the thread stack.
	"""
	_context.request = request


def get_tenant_context() -> typing.Optional[Request]:
	"""
	Extract local context variables for the isolated tenant in
	the thread stack.
	"""
	return getattr(_context, "request", None)


class _WorkspaceContext:
    """Minimal context object for non-HTTP code (Lambda, scripts).

    Mimics the DRF request object enough for ``TenantStorageMixin``
    and ``MediaStorage`` to resolve the workspace.
    """

    def __init__(self, workspace):
        self.workspace = workspace
        self.company = workspace


def set_workspace_context(workspace) -> None:
    """Set tenant context from a Workspace model instance.

    Use in Lambda tasks, management commands, or scripts where
    there is no HTTP request but storage needs tenant scoping.

    Args:
        workspace: A ``Workspace`` model instance.
    """
    _context.request = _WorkspaceContext(workspace)
