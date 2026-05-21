"""
Pydantic schemas for notification payloads.

``NotificationPayload`` is the wire format sent over SSE. Mirrors
narrio's schema so the frontend client can be reused.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


class NotificationPayload(BaseModel):
    """SSE notification payload."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str                                    # "alert" | "info" | "task_update" | ...
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
