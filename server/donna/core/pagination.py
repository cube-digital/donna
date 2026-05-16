"""
Standard pagination classes for the API.

Limit/offset pagination with a response envelope aligned with the legacy FastAPI shape::

    {
        "data": [...],
        "meta": {
            "total": <int>,
            "page": <int>,
            "size": <int|null>,
            "pages": <int>,
            "links": {"first": <url>, "last": <url|null>, "next": <url|null>, "previous": <url|null>}
        },
        "message": "success",
        "code": 0
    }

Query params: ``?limit=100`` (default 100, max 500), ``?offset=0`` (default 0).
"""

from __future__ import annotations

from math import ceil

from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param


class StandardLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500

    def get_paginated_response(self, data):
        total = self.count if self.count is not None else 0
        limit = self.limit
        offset = self.offset

        if not limit:
            page = 1
            pages = 0
        else:
            page = (offset // limit) + 1
            pages = ceil(total / limit) if total else 0

        last_offset = max((pages - 1) * limit, 0) if limit and pages else 0

        return Response(
            {
                "data": data,
                "meta": {
                    "total": total,
                    "page": page,
                    "size": limit,
                    "pages": pages,
                    "links": {
                        "first": self._link_for_offset(0),
                        "last": self._link_for_offset(last_offset) if limit else None,
                        "next": self.get_next_link(),
                        "previous": self.get_previous_link(),
                    },
                },
                "message": "success",
                "code": 0,
            }
        )

    def _link_for_offset(self, offset: int) -> str:
        url = self.request.build_absolute_uri()
        if self.limit is not None:
            url = replace_query_param(url, self.limit_query_param, self.limit)
        return replace_query_param(url, self.offset_query_param, offset)
