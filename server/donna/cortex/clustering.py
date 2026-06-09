"""
Clustering — Subsystem 2 part 2.

Online nearest-centroid assign on write + nightly batch recluster via
Celery beat. Per **spec §6**, clustering scope is the
``(workspace_id, client_id, project_id)`` boundary tuple — clusters
NEVER cross client / project lines.

``HaikuNamer`` mints human-readable cluster names from 5 centroid
samples through ``donna.core.llm``.

Heavy deps (hdbscan, scikit-learn, numpy) are lazy-imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import structlog

from donna.cortex.models import CortexEntity


logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Scope:
    """Boundary contract — the cluster key."""

    workspace_id: UUID
    client_id: UUID | None = None
    project_id: UUID | None = None


class ClusterStrategy(Protocol):
    """Assign rows to clusters (online) + recompute clusters (batch)."""

    def assign(
        self, embedding: list[float], scope: Scope
    ) -> tuple[UUID | None, str | None]: ...

    def recluster(self, scope: Scope) -> dict[UUID, UUID | None]: ...


class ClusterNamerStrategy(Protocol):
    def name(self, sample_texts: list[str]) -> str: ...


class HDBSCANClusterer:
    """Online nearest-centroid + nightly HDBSCAN batch, scope-bounded."""

    def __init__(
        self,
        min_cluster_size: int = 5,
        metric: str = "cosine",
        embedding_dim: int = 384,
    ) -> None:
        self._min_cluster_size = min_cluster_size
        self._metric = metric
        self._embedding_dim = embedding_dim

    # ── online assign ───────────────────────────────────────────────

    def assign(
        self, embedding: list[float], scope: Scope
    ) -> tuple[UUID | None, str | None]:
        centroids = self._compute_centroids(scope)
        if not centroids:
            return None, None

        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError("HDBSCANClusterer.assign requires numpy.") from exc

        emb = np.array(embedding, dtype=np.float32)
        emb /= max(float(np.linalg.norm(emb)), 1e-12)

        best_id: UUID | None = None
        best_name: str | None = None
        best_score = -1.0
        for cluster_id, (centroid, name) in centroids.items():
            c = np.array(centroid, dtype=np.float32)
            c /= max(float(np.linalg.norm(c)), 1e-12)
            score = float(np.dot(emb, c))
            if score > best_score:
                best_score = score
                best_id = cluster_id
                best_name = name

        return best_id, best_name

    # ── batch recluster ─────────────────────────────────────────────

    def recluster(self, scope: Scope) -> dict[UUID, UUID | None]:
        try:
            import hdbscan
            import numpy as np
        except ImportError as exc:
            raise ImportError(
                "HDBSCANClusterer.recluster requires hdbscan + numpy."
            ) from exc

        rows = list(
            self._scoped_queryset(scope)
            .filter(doc_embedding__isnull=False)
            .values_list("id", "doc_embedding")
        )
        if not rows:
            return {}

        ids = [r[0] for r in rows]
        embeddings = np.array([r[1] for r in rows], dtype=np.float32)

        model = hdbscan.HDBSCAN(
            min_cluster_size=self._min_cluster_size,
            metric=self._metric,
        )
        labels = model.fit_predict(embeddings)

        # Map integer labels → deterministic UUIDs scoped per
        # (workspace, client, project). Same label across runs → same
        # UUID, so cluster identity persists.
        import uuid as _uuid

        ns = _uuid.uuid5(
            _uuid.NAMESPACE_URL,
            f"cortex-cluster:{scope.workspace_id}:{scope.client_id}:{scope.project_id}",
        )
        return {
            entity_id: (
                None
                if int(label) == -1
                else _uuid.uuid5(ns, str(int(label)))
            )
            for entity_id, label in zip(ids, labels)
        }

    # ── internals ───────────────────────────────────────────────────

    def _scoped_queryset(self, scope: Scope):
        qs = CortexEntity.objects.filter(workspace_id=scope.workspace_id)
        qs = (
            qs.filter(client_id=scope.client_id)
            if scope.client_id is not None
            else qs.filter(client_id__isnull=True)
        )
        qs = (
            qs.filter(project_id=scope.project_id)
            if scope.project_id is not None
            else qs.filter(project_id__isnull=True)
        )
        return qs

    def _compute_centroids(
        self, scope: Scope
    ) -> dict[UUID, tuple[list[float], str]]:
        try:
            import numpy as np
        except ImportError:
            return {}

        out: dict[UUID, dict] = {}
        qs = (
            self._scoped_queryset(scope)
            .filter(doc_embedding__isnull=False, cluster_id__isnull=False)
            .values("cluster_id", "doc_embedding", "extensions")
        )
        for row in qs:
            cluster_id: UUID | None = row["cluster_id"]
            if cluster_id is None:
                continue
            ext = row.get("extensions") or {}
            slot = out.setdefault(
                cluster_id,
                {
                    "sum": np.zeros(self._embedding_dim, dtype=np.float32),
                    "n": 0,
                    "name": ext.get("cluster_name", ""),
                },
            )
            slot["sum"] += np.array(row["doc_embedding"], dtype=np.float32)
            slot["n"] += 1

        return {
            cid: ((slot["sum"] / max(slot["n"], 1)).tolist(), slot["name"])
            for cid, slot in out.items()
            if slot["n"] > 0
        }


class HaikuNamer:
    """Cluster naming via Anthropic Haiku (LiteLLM)."""

    DEFAULT_MODEL = "anthropic/claude-3-5-haiku-latest"
    DEFAULT_PROMPT = (
        "Given the following short text excerpts from documents that "
        "share a latent topic, propose a 2-4 word descriptive name "
        "for the topic. Output ONLY the name, nothing else.\n\n"
    )

    def __init__(self, model: str | None = None) -> None:
        self._model = model or self.DEFAULT_MODEL

    def name(self, sample_texts: list[str]) -> str:
        from donna.core.llm.factory import LLMFactory

        provider = LLMFactory.create(model=self._model)
        joined = "\n\n---\n\n".join(
            f"Excerpt {i + 1}:\n{t[:500]}"
            for i, t in enumerate(sample_texts[:5])
        )
        response = provider.chat(
            messages=[
                {"role": "user", "content": self.DEFAULT_PROMPT + joined},
            ],
            temperature=0.2,
        )
        raw = response.content
        return (raw if isinstance(raw, str) else str(raw)).strip().strip(".")


class ClusteringService:
    """Compose embedder + clusterer + namer behind one boundary."""

    def __init__(
        self,
        embedder,
        clusterer: ClusterStrategy,
        namer: ClusterNamerStrategy,
    ) -> None:
        self._embedder = embedder
        self._clusterer = clusterer
        self._namer = namer

    def assign(
        self, *, body_md: str, scope: Scope
    ) -> tuple[list[float], UUID | None, str | None]:
        """One call for ``CortexWriter`` step 5.

        Returns ``(embedding, cluster_id, cluster_name)``.
        """
        embedding = self._embedder.embed(body_md)
        cluster_id, cluster_name = self._clusterer.assign(embedding, scope)
        return embedding, cluster_id, cluster_name
