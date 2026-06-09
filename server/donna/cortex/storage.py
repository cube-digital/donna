"""
SilverStorage Protocol + LocalFSStorage implementation.

Per **Cortex Universal Silver Specification v1 (rev 3) §8**.

The Cortex layer's canonical store lives in **files**, not Postgres
(spec §14 — "Postgres = derived index"). This module defines the
single Protocol that all three locked backends honour:

- ``GitHubStorage`` — single-commit atomicity via Git Trees API
- ``S3Storage`` — multipart batch + DynamoDB write-lock
- ``LocalFSStorage`` — flock + rename (dev / single-user)

Only ``LocalFSStorage`` ships in this revision; the other two land
when first cloud / self-host clients onboard. All three speak the
identical Protocol so workspace migration between backends is a
config flip (spec §8.2).

The default-storage Django facade is NOT the SilverStorage — that
backs the Bronze blobs. Silver writes happen through this Protocol.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Protocol
from uuid import UUID


# ── Result types ───────────────────────────────────────────────────


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a single ``write`` call."""

    entity_id: UUID
    path: str
    version: str  # commit sha / S3 version / local mtime ISO


@dataclass(frozen=True)
class ReverseEdgeUpdate:
    """Reverse-edge mutation applied atomically alongside the entity write."""

    target_entity_id: UUID
    edge_field: str  # "applied_in" / "superseded_by" / "contradicts"
    value: UUID  # the id being appended (or assigned)


@dataclass(frozen=True)
class Version:
    """One historical version returned by ``history()``."""

    version: str
    written_at: datetime
    author: str | None = None
    message: str | None = None


# ── Protocol (canonical surface) ───────────────────────────────────


class SilverStorage(Protocol):
    """Canonical Silver lives in files. Postgres is a derived index."""

    async def write(
        self,
        entity: Any,  # SilverEntity — Any here to avoid import cycle
        reverse_edges: Iterable[ReverseEdgeUpdate],
    ) -> WriteResult:
        """Atomic write: entity file + every reverse-edge target file."""
        ...

    async def read(self, entity_id: UUID) -> Any:
        """Load the entity by id (path looked up via index or by walking)."""
        ...

    async def list(
        self,
        prefix: str,
        since: datetime | None = None,
    ) -> list[str]:
        """List paths under ``prefix`` (relative); used for cold-start rebuild."""
        ...

    async def delete(self, entity_id: UUID) -> None:
        """Hard delete; rare. Use ``supersedes`` for replacements instead."""
        ...

    async def history(self, entity_id: UUID) -> list[Version]:
        """Backend-native version log (git log / S3 versions / fs mtime)."""
        ...


# ── LocalFSStorage (dev / single-user offline) ─────────────────────


class LocalFSStorage:
    """File-backed Silver storage with ``flock`` + atomic rename.

    Layout matches spec §9 Universal Folder Structure. Each
    ``SilverEntity`` is one ``.md`` file with YAML frontmatter +
    rendered body.

    Atomicity: write to a sibling tempfile + ``os.rename`` (POSIX
    atomic) + ``flock`` on the parent index file. Cross-file
    reverse-edge updates are serialised through a workspace-wide
    ``.cortex/write.lock`` flock so a single writer at a time can
    touch the tree. Coarse but sufficient for single-user dev.

    For multi-process production, use ``GitHubStorage`` or
    ``S3Storage``.
    """

    LOCK_FILENAME = ".cortex-write.lock"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    async def write(
        self,
        entity: Any,
        reverse_edges: Iterable[ReverseEdgeUpdate],
    ) -> WriteResult:
        """Write the entity file + apply each reverse-edge update.

        Atomic per file. Cross-file ordering is enforced by the
        workspace-wide lock. If any step fails, the lock release
        leaves the tree in an inconsistent state (no rollback) — use
        ``GitHubStorage`` if you need true cross-file atomicity.
        """
        path = self._path_for(entity)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = self._serialise(entity)

        lock_path = self._root / self.LOCK_FILENAME
        with self._exclusive_lock(lock_path):
            self._atomic_write(path, body)
            for update in reverse_edges:
                self._apply_reverse_edge(update)

        return WriteResult(
            entity_id=entity.id,
            path=str(path.relative_to(self._root)),
            version=datetime.utcnow().isoformat(timespec="seconds"),
        )

    async def read(self, entity_id: UUID) -> Any:
        for path in self._root.rglob("*.md"):
            try:
                payload = self._parse(path.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("id") == str(entity_id):
                return payload
        raise FileNotFoundError(f"No entity {entity_id} under {self._root}")

    async def list(
        self,
        prefix: str,
        since: datetime | None = None,
    ) -> list[str]:
        prefix_path = self._root / prefix
        if not prefix_path.exists():
            return []
        out: list[str] = []
        for p in prefix_path.rglob("*.md"):
            if since and datetime.fromtimestamp(p.stat().st_mtime) < since:
                continue
            out.append(str(p.relative_to(self._root)))
        return sorted(out)

    async def delete(self, entity_id: UUID) -> None:
        for p in self._root.rglob("*.md"):
            try:
                payload = self._parse(p.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("id") == str(entity_id):
                p.unlink()
                return

    async def history(self, entity_id: UUID) -> list[Version]:
        # POSIX mtime only — for real history use GitHubStorage.
        for p in self._root.rglob("*.md"):
            try:
                payload = self._parse(p.read_text("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("id") == str(entity_id):
                ts = datetime.fromtimestamp(p.stat().st_mtime)
                return [Version(version=ts.isoformat(), written_at=ts)]
        return []

    # ── internals ───────────────────────────────────────────────────

    def _path_for(self, entity: Any) -> Path:
        """Compute the canonical file path for ``entity``.

        Relies on ``entity.extensions['parent_path']`` and
        ``entity.extensions['slug']`` set by ``CortexWriter`` step 6.
        """
        ext = getattr(entity, "extensions", {}) or {}
        parent = ext.get("parent_path", "_inbox").lstrip("/")
        slug = ext.get("slug", str(entity.id))
        return self._root / parent / f"{slug}.md"

    def _serialise(self, entity: Any) -> str:
        return getattr(entity, "body_md", "") or ""

    def _parse(self, text: str) -> dict[str, Any]:
        # Frontmatter parser stub — used by ``read()``. Full YAML
        # parsing arrives with the MCP API (P9).
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        out: dict[str, Any] = {}
        for line in parts[1].splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
        return out

    def _atomic_write(self, path: Path, body: str) -> None:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".cortex-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(tmp_name, path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _apply_reverse_edge(self, update: ReverseEdgeUpdate) -> None:
        # Find target file by id, patch its frontmatter JSON edge
        # array. The full implementation reuses the same parse/render
        # pipeline as ``write``; left as a stub until MCP API ships.
        pass  # TODO(P9): patch target frontmatter atomically

    @staticmethod
    def _exclusive_lock(path: Path):
        """Return a context manager that holds an exclusive flock."""
        import fcntl
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

        return _ctx()
