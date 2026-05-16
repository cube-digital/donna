"""
Standard JSON response envelope for the API.

Successful responses are wrapped as::

    {"data": <payload>, "meta": {}, "message": "success", "code": 0}

Paginated list responses and error bodies are produced by pagination / the
exception handler and are passed through without double-wrapping.
"""

from __future__ import annotations

from typing import Any

from rest_framework.renderers import JSONRenderer


def is_standard_envelope(data: Any) -> bool:
    """True when *data* is already a full top-level API envelope."""
    if not isinstance(data, dict):
        return False
    return {"data", "meta", "message", "code"}.issubset(data.keys())


class StandardJSONRenderer(JSONRenderer):
    """
    Wraps successful JSON responses in the standard envelope.

    Skips wrapping when the payload is already an envelope (pagination or
    pre-formatted error from the exception handler).
    """

    charset = "utf-8"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes | str:
        if renderer_context is None:
            renderer_context = {}
        response = renderer_context.get("response")

        if (
            response is not None
            and response.status_code < 400
            and not is_standard_envelope(data)
        ):
            data = {
                "data": data,
                "meta": {},
                "message": "success",
                "code": 0,
            }

        return super().render(data, accepted_media_type, renderer_context)
