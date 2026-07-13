"""CortexService — read/write API over the silver layer (Phase 4).

The first real customer is the chat agent (00j A1). Surface kept
deliberately small: query, read_entity, get_context. Write helpers
(create_entity, linter_check) land alongside drafting (A2).

**Hybrid retrieval** (Phase 4, Q&A slice 2026-06-12)
RRF fusion over two channels — dense cosine on ``doc_embedding`` +
keyword match on ``title``/``extensions``. tsvector + sparsevec
channels are deferred to Phase 7 stretch (00f) — both require new
indexes + a migration; this slice ships without either so the test
recipe doesn't depend on infra changes.

**Graceful degradation:** when no entity in the result set has a
``doc_embedding`` (e.g. embeddings disabled for dev), the dense channel
short-circuits and the keyword channel carries the query alone.

Plain English: caller passes free text + optional filters (type,
client, scope). Service returns ranked entity headers — title, snippet,
source URI, score — that the chat agent cites in answers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from django.db.models import Q

from donna.core.services import BaseService
from donna.cortex.embeddings import BGESmallEmbedder
from donna.cortex.models import CortexEntity


logger = logging.getLogger(__name__)


# ── Result types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueryHit:
    """One ranked entity in a query result set."""

    id: UUID
    type: str
    title: str
    source: str
    occurred_at: str
    score: float
    snippet: str
    client_id: UUID | None
    project_id: UUID | None

    def summary(self) -> dict:
        """Compact dict for tool result payloads — the agent sees this."""
        return {
            "id": str(self.id),
            "type": self.type,
            "title": self.title,
            "source": self.source,
            "occurred_at": self.occurred_at,
            "score": round(self.score, 4),
            "snippet": self.snippet,
            "client_id": str(self.client_id) if self.client_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
        }


@dataclass(frozen=True)
class EntityCard:
    """Full entity read — header + body + edges."""

    id: UUID
    type: str
    title: str
    source: str
    occurred_at: str
    body_md: str
    extensions: dict
    entity_refs: list[str]
    sources: list[str]
    cross_refs: list[str]
    client_id: UUID | None
    project_id: UUID | None
    bronze_storage_key: str = ""

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "type": self.type,
            "title": self.title,
            "source": self.source,
            "occurred_at": self.occurred_at,
            "body_md": self.body_md,
            "extensions": self.extensions,
            "entity_refs": self.entity_refs,
            "sources": self.sources,
            "cross_refs": self.cross_refs,
            "client_id": str(self.client_id) if self.client_id else None,
            "project_id": str(self.project_id) if self.project_id else None,
            "bronze_storage_key": self.bronze_storage_key,
        }


# ── Service ─────────────────────────────────────────────────────────


class CortexService(BaseService[CortexEntity]):
    """Read/write API over CortexEntity heads (superseded rows hidden).

    ``current_user`` and ``company`` come from middleware (see
    ``BaseService.__init__``); ``company`` is the active workspace.
    """

    model_class = CortexEntity

    # RRF constant — Cormack-Clarke-Buettcher k=60 default; tune later.
    _RRF_K = 60
    # Dense candidate pool — over-fetch then rerank. 10× target.
    _DENSE_FETCH = 50
    # Keyword candidate pool.
    _KEYWORD_FETCH = 50
    # Max snippet chars in result.
    _SNIPPET_CHARS = 240

    def __init__(self, current_user=None, company=None, embedder=None) -> None:
        super().__init__(current_user=current_user, company=company)
        # Lazy embedder — only loaded when query() actually needs it.
        # Tests inject a stub. Production gets BGESmallEmbedder default.
        self._embedder = embedder

    # ── query ───────────────────────────────────────────────────────

    def query(
        self,
        *,
        text: str,
        type: str | None = None,
        doc_type: str | None = None,
        client_id: UUID | None = None,
        project_id: UUID | None = None,
        relationship: str | None = None,
        limit: int = 8,
    ) -> list[QueryHit]:
        """Hybrid retrieval — dense + keyword, RRF-fused, heads-only.

        Metadata filters apply FIRST (type, doc_type, client, project,
        relationship) — narrows the candidate set before scoring per
        prod-grade RAG guidance (00l field study).

        ``relationship`` filters via the entity's ``client_id`` org's
        ``extensions.relationship`` — e.g. ``relationship="client"``
        returns only entities scoped to orgs tagged as clients,
        excluding vendor / partner / peer noise.
        """
        if not text or not text.strip():
            return []

        workspace_id = self.company.id if self.company is not None else None
        if workspace_id is None:
            return []

        base = self._filtered_heads(
            workspace_id=workspace_id,
            type=type,
            doc_type=doc_type,
            client_id=client_id,
            project_id=project_id,
            relationship=relationship,
        )

        dense_ranking = self._dense_channel(text=text, qs=base)
        keyword_ranking = self._keyword_channel(text=text, qs=base)
        tsvector_ranking = self._tsvector_channel(text=text, qs=base)

        fused = self._rrf_fuse([dense_ranking, keyword_ranking, tsvector_ranking])
        if not fused:
            return []

        top_ids = [eid for eid, _ in fused[:limit]]
        # Re-fetch in score order for stable ranking. select_related the
        # workspace is unnecessary; we already filter on it.
        rows_by_id = {
            r.id: r
            for r in CortexEntity.objects.filter(id__in=top_ids)
        }
        out: list[QueryHit] = []
        for entity_id, score in fused[:limit]:
            row = rows_by_id.get(entity_id)
            if row is None:
                continue
            out.append(self._to_hit(row, score))
        return out

    # ── read_entity ────────────────────────────────────────────────

    def read_entity(
        self,
        entity_id: UUID | str,
        *,
        include_body: bool = True,
    ) -> EntityCard | None:
        """Full entity payload by id. Returns None on miss / cross-workspace."""
        workspace_id = self.company.id if self.company is not None else None
        if workspace_id is None:
            return None
        try:
            row = CortexEntity.objects.get(id=entity_id, workspace_id=workspace_id)
        except CortexEntity.DoesNotExist:
            return None
        body_md = row.load_body() if include_body else ""
        return EntityCard(
            id=row.id,
            type=row.type,
            title=row.title,
            source=row.source,
            occurred_at=row.occurred_at.isoformat() if row.occurred_at else "",
            body_md=body_md,
            extensions=row.extensions or {},
            entity_refs=[str(x) for x in (row.entity_refs or [])],
            sources=[str(x) for x in (row.sources or [])],
            cross_refs=[str(x) for x in (row.cross_refs or [])],
            client_id=row.client_id,
            project_id=row.project_id,
            bronze_storage_key=row.bronze_storage_key or "",
        )

    # ── get_context ────────────────────────────────────────────────

    def get_context(
        self,
        entity_id: UUID | str,
        *,
        depth: int = 1,
    ) -> list[EntityCard]:
        """Neighbors via entity_refs + sources, capped at depth (1 or 2).

        Depth 1 = direct neighbors. Depth 2 = neighbors of neighbors,
        deduped. Bounded for context-budget safety.
        """
        workspace_id = self.company.id if self.company is not None else None
        if workspace_id is None:
            return []
        depth = max(1, min(depth, 2))

        seed = self.read_entity(entity_id, include_body=False)
        if seed is None:
            return []

        seen: set[str] = {str(seed.id)}
        frontier: list[str] = list(set(seed.entity_refs + seed.sources))
        cards: list[EntityCard] = []

        for _ in range(depth):
            next_frontier: list[str] = []
            for neighbor_id in frontier:
                if neighbor_id in seen:
                    continue
                seen.add(neighbor_id)
                card = self.read_entity(neighbor_id, include_body=False)
                if card is None:
                    continue
                cards.append(card)
                next_frontier.extend(card.entity_refs + card.sources)
            frontier = next_frontier
            if not frontier:
                break
        return cards

    # ── write API (P4a, 2026-06-15) ────────────────────────────────

    def create_entity(
        self,
        *,
        type: str,
        author: str,
        source: str,
        title: str,
        body_md: str,
        extensions: dict | None = None,
        occurred_at=None,
        client_id: UUID | None = None,
        project_id: UUID | None = None,
        bronze_storage_key: str = "",
    ):
        """Direct write API — lints + persists with reverse-edge atomicity.

        Used by the chat agent (A2 FinalizeDraftTool) and the MCP server.
        body_md must include the ``Source: <uri>`` or ``Spawned by: ...``
        footer required by the linter; caller assembles it.
        """
        import hashlib
        from datetime import datetime, timezone
        from uuid import uuid4

        from donna.cortex.linter import FrontmatterLinter
        from donna.cortex.models import CortexEntity

        if self.company is None:
            raise ValueError("CortexService.create_entity requires company context")
        workspace_id = self.company.id

        body_bytes = body_md.encode("utf-8")
        content_hash = hashlib.sha256(body_bytes).hexdigest()
        now = datetime.now(tz=timezone.utc)

        entity = CortexEntity(
            id=uuid4(),
            workspace_id=workspace_id,
            type=type,
            author=author,
            source=source,
            bronze_storage_key=bronze_storage_key,
            content_hash=content_hash,
            occurred_at=occurred_at or now,
            client_id=client_id,
            project_id=project_id,
            title=title,
            body_byte_size=len(body_bytes),
            confidence="high",
            last_synthesized=now.date(),
            extensions=extensions or {},
        )
        FrontmatterLinter().check(entity, body_md=body_md)
        return CortexEntity.objects.save_with_reverse_edges(
            entity, body_bytes=body_bytes
        )

    def linter_check(
        self,
        *,
        type: str,
        body_md: str,
        extensions: dict,
        title: str = "draft",
    ):
        """Run the FrontmatterLinter against an in-memory candidate row.

        Returns a small verdict object: ``.ok`` + ``.codes`` (rejected
        codes for the agent to react to). Used by FinalizeDraftTool (A2).
        """
        from datetime import datetime, timezone
        from uuid import uuid4

        from donna.cortex.linter import FrontmatterLinter, LinterError

        workspace_id = self.company.id if self.company is not None else uuid4()
        candidate = CortexEntity(
            id=uuid4(),
            type=type,
            author="agent",
            source="donna://draft/pending",
            content_hash="0" * 64,
            occurred_at=datetime.now(tz=timezone.utc),
            workspace_id=workspace_id,
            title=title,
            extensions=extensions or {},
        )
        try:
            FrontmatterLinter().check(candidate, body_md=body_md)
            return _LinterVerdict(ok=True, codes=[])
        except LinterError as exc:
            return _LinterVerdict(ok=False, codes=[exc.code])

    # ── internals ──────────────────────────────────────────────────

    def _filtered_heads(
        self,
        *,
        workspace_id: UUID,
        type: str | None,
        doc_type: str | None,
        client_id: UUID | None,
        project_id: UUID | None,
        relationship: str | None = None,
    ):
        # Heads-only — superseded rows are invisible to retrieval per R1.
        qs = CortexEntity.objects.filter(
            workspace_id=workspace_id,
            superseded_by__isnull=True,
        )
        if type:
            qs = qs.filter(type=type)
        if doc_type:
            qs = qs.filter(extensions__doc_type=doc_type)
        if client_id is not None:
            qs = qs.filter(client_id=client_id)
        if project_id is not None:
            qs = qs.filter(project_id=project_id)
        if relationship is not None:
            # Filter via the scope-client org's relationship.
            # An entity's client_id points to an org row; we want only
            # those where that org has the given relationship tag.
            client_ids_in_rel = list(
                CortexEntity.objects
                .filter(
                    workspace_id=workspace_id,
                    type="org",
                    extensions__relationship=relationship,
                )
                .values_list("id", flat=True)
            )
            if not client_ids_in_rel:
                # Empty filter shortcut — no orgs match this relationship,
                # so no entities can match either.
                return qs.none()
            qs = qs.filter(client_id__in=client_ids_in_rel)
        return qs

    def _dense_channel(self, *, text: str, qs) -> list[tuple[UUID, float]]:
        """Cosine ranking against ``doc_embedding`` for rows that have one.

        Degrades to empty list if no embedder available OR no row has
        an embedding (dev/test paths without sentence-transformers).
        """
        try:
            from pgvector.django import CosineDistance
        except ImportError:
            return []

        embedded_qs = qs.filter(doc_embedding__isnull=False)
        # Quick existence probe — avoids loading the embedder on cold DB.
        if not embedded_qs.exists():
            return []

        embedder = self._get_embedder()
        if embedder is None:
            return []
        try:
            query_vec = embedder.embed(text)
        except Exception:  # noqa: BLE001 — model load failures are real
            logger.exception("dense_channel_embed_failed", extra={"text": text[:80]})
            return []

        rows = list(
            embedded_qs.annotate(_dist=CosineDistance("doc_embedding", query_vec))
            .order_by("_dist")
            .values_list("id", "_dist")[: self._DENSE_FETCH]
        )
        # Cosine *distance* → similarity = 1 - distance. Score asc here
        # used only for RRF ranking; RRF cares about position, not absolute.
        return [(row[0], 1.0 - float(row[1])) for row in rows]

    def _keyword_channel(self, *, text: str, qs) -> list[tuple[UUID, float]]:
        """Cheap ILIKE on title; full tsvector deferred to Phase 7 stretch."""
        # Tokenize naively — split on whitespace, drop very short stopword-ish.
        terms = [t for t in text.lower().split() if len(t) > 2][:6]
        if not terms:
            return []
        q = Q()
        for t in terms:
            q |= Q(title__icontains=t)
        rows = list(
            qs.filter(q)
            .order_by("-occurred_at")
            .values_list("id", "title")[: self._KEYWORD_FETCH]
        )
        # Score = how many terms match in the title (cheap relevance proxy).
        scored: list[tuple[UUID, float]] = []
        for entity_id, title in rows:
            title_lower = (title or "").lower()
            hits = sum(1 for t in terms if t in title_lower)
            if hits:
                scored.append((entity_id, float(hits)))
        scored.sort(key=lambda x: -x[1])
        return scored

    def _tsvector_channel(self, *, text: str, qs) -> list[tuple[UUID, float]]:
        """Postgres full-text channel — title + extensions::text.

        Phase 4 (2026-06-15): uses Django's ``SearchVector`` +
        ``SearchRank`` over (title, extensions cast to text). Bodies
        live in SilverStorage so they're NOT in this channel — Phase 7
        adds a denormalized text column for body indexing. Today's
        coverage is title-and-metadata; combined with the dense channel
        + simple ILIKE keyword channel that fills the rest.
        """
        try:
            from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
        except ImportError:
            return []
        try:
            vec = (
                SearchVector("title", weight="A")
                + SearchVector("source", weight="B")
            )
            q = SearchQuery(text, search_type="websearch")
            rows = list(
                qs.annotate(_rank=SearchRank(vec, q))
                .filter(_rank__gt=0.0)
                .order_by("-_rank")
                .values_list("id", "_rank")[: self._KEYWORD_FETCH]
            )
        except Exception:  # noqa: BLE001 — sqlite tests, missing extension, etc.
            return []
        return [(row[0], float(row[1])) for row in rows]

    def _rrf_fuse(
        self,
        rankings: Iterable[list[tuple[UUID, float]]],
        k: int | None = None,
    ) -> list[tuple[UUID, float]]:
        """Reciprocal rank fusion — RRF score = sum(1/(k + rank))."""
        k = k or self._RRF_K
        fused: dict[UUID, float] = {}
        for ranking in rankings:
            for rank, (entity_id, _) in enumerate(ranking, start=1):
                fused[entity_id] = fused.get(entity_id, 0.0) + 1.0 / (k + rank)
        return sorted(fused.items(), key=lambda x: -x[1])

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        try:
            self._embedder = BGESmallEmbedder()
        except Exception:  # noqa: BLE001
            logger.warning("embedder_unavailable; dense channel disabled")
            return None
        return self._embedder

    def _to_hit(self, row: CortexEntity, score: float) -> QueryHit:
        snippet = (row.title or "")[: self._SNIPPET_CHARS]
        return QueryHit(
            id=row.id,
            type=row.type,
            title=row.title or "",
            source=row.source or "",
            occurred_at=row.occurred_at.isoformat() if row.occurred_at else "",
            score=score,
            snippet=snippet,
            client_id=row.client_id,
            project_id=row.project_id,
        )


@dataclass(frozen=True)
class _LinterVerdict:
    ok: bool
    codes: list[str]
