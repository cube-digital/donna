"""Versioned bronze storage helpers (Phase 1 — 2026-06-12, expanded 2026-06-15).

Bronze blobs are immutable: every distinct payload lands at a unique
key carrying ``sha8(content)`` in the path. Re-ingest never overwrites;
identical content collides on the hash → idempotent. Distinct content
for the same source/item produces a new key and the old payload stays
addressable for replay / supersession reconciliation.

The ``.extracted.md`` sidecar (2026-06-15) is a *body-only* render of
the connector's adapter output saved next to the JSON blob. The
cortex pipeline prefers it over re-rendering the body from raw JSON
on every read — same content lives in two places (raw + extracted)
but the read path stays cheap and predictable.
"""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath


def bronze_key(
    workspace_id: str,
    provider: str,
    kind: str,
    item_id: str,
    content: bytes,
) -> str:
    """Versioned bronze key — same content → same key, new content → new key.

    Layout: ``<workspace_id>/<provider>/<kind>/<item_id>/<sha8>.json``
    """
    sha8 = hashlib.sha256(content).hexdigest()[:8]
    return f"{workspace_id}/{provider}/{kind}/{item_id}/{sha8}.json"


def sidecar_key_for(bronze_storage_key: str) -> str:
    """Return the ``.extracted.md`` sidecar key paired with a bronze JSON.

    Layout: ``<bronze_dir>/<bronze_stem>.extracted.md`` — same folder,
    swap suffix. The sidecar is regenerated every time the bronze is
    written, so the (bronze, sidecar) pair stays in sync.
    """
    path = PurePosixPath(bronze_storage_key)
    return str(path.with_suffix(".extracted.md"))


def write_sidecar(storage, bronze_storage_key: str, body_md: str) -> str:
    """Write the ``.extracted.md`` sidecar next to ``bronze_storage_key``.

    Idempotent — if a sidecar already exists at the computed path
    (same content was bronze-written before), skip. Returns the
    sidecar key for the caller's logs.
    """
    from django.core.files.base import ContentFile

    key = sidecar_key_for(bronze_storage_key)
    if not storage.exists(key):
        storage.save(key, ContentFile(body_md.encode("utf-8")))
    return key
