"""
BaseHTTPClient — the HTTP wrapper every connector subclasses.

Provides:
- Auth header injection (Bearer by default; override `_auth_headers`)
- Standard retry on transient errors (5xx, network)
- JSON request/response handling
- Pagination helpers

Subclasses set `base_url` and implement endpoint-specific methods.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterator

import httpx

if TYPE_CHECKING:
    from donna.authentication.models import OAuthToken


logger = logging.getLogger(__name__)


# Transient HTTP statuses worth retrying.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class BaseHTTPClient:
    """
    Base HTTP client for integration connectors.

    Usage in a subclass:
        class FathomClient(BaseHTTPClient):
            base_url = "https://api.fathom.video/external/v1"

            def get_meeting(self, meeting_id: str) -> dict:
                return self.get(f"/meetings/{meeting_id}")
    """

    base_url: str = ""
    timeout: float = 30.0
    max_retries: int = 3

    def __init__(self, token: "OAuthToken | None" = None):
        self.token = token
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    # ── Auth ─────────────────────────────────────────────────────────────────
    def _auth_headers(self) -> dict[str, str]:
        """
        Build auth headers from the bound OAuthToken. Override for non-Bearer
        schemes (e.g., Slack's bot tokens with different header conventions).
        """
        if self.token is None or not getattr(self.token, "access_token", None):
            return {}
        return {"Authorization": f"Bearer {self.token.access_token}"}

    # ── Core request ─────────────────────────────────────────────────────────
    def request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an HTTP request with auth headers, retries, and JSON parsing."""
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(self._auth_headers())
        kwargs["headers"] = headers

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "http_transport_error",
                    extra={"attempt": attempt, "method": method, "path": path, "error": str(exc)},
                )
                if attempt == self.max_retries:
                    raise
                continue

            if response.status_code in _RETRY_STATUSES and attempt < self.max_retries:
                logger.warning(
                    "http_retry_status",
                    extra={
                        "attempt": attempt,
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                    },
                )
                continue

            response.raise_for_status()
            return self._parse_response(response)

        # All retries exhausted on transport errors
        assert last_exc is not None
        raise last_exc

    def _parse_response(self, response: httpx.Response) -> dict:
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            # Non-JSON body — wrap as `{"_raw": "..."}` so callers can still proceed.
            return {"_raw": response.text}

    # ── Convenience verbs ────────────────────────────────────────────────────
    def get(self, path: str, params: dict | None = None, **kw: Any) -> dict:
        return self.request("GET", path, params=params, **kw)

    def post(self, path: str, json: dict | None = None, **kw: Any) -> dict:
        return self.request("POST", path, json=json, **kw)

    def put(self, path: str, json: dict | None = None, **kw: Any) -> dict:
        return self.request("PUT", path, json=json, **kw)

    def delete(self, path: str, **kw: Any) -> dict:
        return self.request("DELETE", path, **kw)

    # ── Pagination helper ────────────────────────────────────────────────────
    def paginate_cursor(
        self,
        path: str,
        *,
        params: dict | None = None,
        cursor_param: str = "cursor",
        cursor_field: str = "next_cursor",
        items_field: str = "items",
    ) -> Iterator[dict]:
        """
        Generic cursor pagination — yields each item across pages.

        Override or wrap in subclasses when the API uses a different shape.
        """
        params = dict(params or {})
        cursor: str | None = None
        while True:
            if cursor is not None:
                params[cursor_param] = cursor
            page = self.get(path, params=params)
            for item in page.get(items_field, []):
                yield item
            cursor = page.get(cursor_field)
            if not cursor:
                return

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BaseHTTPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
