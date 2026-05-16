"""
Maps DRF and Django exceptions to the standard API error envelope.

Success shape (reference)::

    {"data": ..., "meta": {}, "message": "success", "code": 0}

Error shape::

    {"data": null | {<field>: {"message": str, "type": str}}, "meta": {}, "message": str, "code": <http_status>}
"""

from __future__ import annotations

from typing import Any

from rest_framework.views import exception_handler as drf_exception_handler


def _first_error_message(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _first_error_message(value[0])
    if isinstance(value, dict):
        if "message" in value:
            return str(value["message"])
        return str(next(iter(value.values()), ""))
    return str(value)


def _format_field_errors(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Turn DRF validation errors into {field: {message, type}}."""
    out: dict[str, dict[str, str]] = {}
    for field, errors in data.items():
        out[field] = {
            "message": _first_error_message(errors),
            "type": "validation_error",
        }
    return out


def _looks_like_validation_errors(data: dict[str, Any]) -> bool:
    """Heuristic: field-keyed validation payload vs a single ``detail`` blob."""
    if not data:
        return False
    if set(data.keys()) <= {"detail"}:
        return False
    for key, value in data.items():
        if key in ("detail", "code"):
            continue
        if isinstance(value, (list, dict)):
            return True
    return False


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Any:
    """Wrap DRF default handler output in the standard envelope."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    status_code = response.status_code
    raw: Any = response.data

    if isinstance(raw, dict):
        if _looks_like_validation_errors(raw):
            # Drop bare ``detail`` if present alongside field errors
            fields = {k: v for k, v in raw.items() if k not in ("detail", "code")}
            response.data = {
                "data": _format_field_errors(fields) if fields else None,
                "meta": {},
                "message": "Validation Error",
                "code": status_code,
            }
            return response

        if "detail" in raw:
            detail = raw["detail"]
            if isinstance(detail, list):
                message = _first_error_message(detail)
            else:
                message = str(detail)
            extra = {k: v for k, v in raw.items() if k not in ("detail",)}
            meta: dict[str, Any] = {}
            if extra:
                meta["extra"] = extra
            response.data = {
                "data": None,
                "meta": meta,
                "message": message,
                "code": status_code,
            }
            return response

    if isinstance(raw, list):
        response.data = {
            "data": None,
            "meta": {},
            "message": _first_error_message(raw) if raw else "Error",
            "code": status_code,
        }
        return response

    if isinstance(raw, str):
        response.data = {
            "data": None,
            "meta": {},
            "message": raw,
            "code": status_code,
        }
        return response

    # Fallback
    response.data = {
        "data": raw,
        "meta": {},
        "message": "HTTP Error",
        "code": status_code,
    }
    return response
