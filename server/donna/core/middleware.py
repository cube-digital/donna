"""
Django middleware for structured logging and multi-tenant context.

Provides:
- Request context propagation for all logs within a request lifecycle.
- Tenant resolution from ``X-Tenant-Id`` header or user membership.
"""

import time

from django.http import Http404
from django.utils.functional import SimpleLazyObject

from docupal.core.logging import (
    clear_request_context,
    get_logger,
    set_request_context,
    update_request_context,
)

logger = get_logger(__name__)


class LoggingMiddleware:
    """
    Middleware to set up request context for structured logging.

    Sets request_id, operation, and timing information for each request.
    Should be placed early in the middleware stack.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.perf_counter()

        # Extract request ID from header or generate new one
        request_id = request.headers.get("X-Request-ID")

        # Set initial context
        request_id = set_request_context(
            request_id=request_id,
            operation=f"{request.method} {request.path}",
        )

        # Store request_id on request object for access in views
        request.request_id = request_id

        # Process the request
        response = self.get_response(request)

        # Add request ID to response headers
        response["X-Request-ID"] = request_id

        # Clear context after request
        clear_request_context()

        return response
