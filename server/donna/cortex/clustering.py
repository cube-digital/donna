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

# ── __main__ bootstrap ──────────────────────────────────────────────
# When invoked as `python -m donna.cortex.clustering`, `__name__` is
# "__main__" from line one. Bootstrap Django here, BEFORE the ORM-bound
# imports below, so the model class can load. We do NOT run migrations
# — the demo mocks DB access (Cortex models use pgvector, which only
# the real Postgres dev DB has).
if __name__ == "__main__":
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "donna.settings")
    import django
    django.setup()

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


if __name__ == "__main__":
    # Run: `python -m donna.cortex.clustering` (from `server/`)
    # Django was bootstrapped at the top of the module.
    # DB-bound paths are mocked via a subclass (see _MockHDBSCAN below)
    # because Cortex models require pgvector — only the real Postgres
    # dev DB satisfies that.
    from uuid import uuid4, uuid5, NAMESPACE_URL

    ws = uuid4()
    client = uuid4()

    print("── Scope (frozen dataclass) ─────────────────────────────────")
    s1 = Scope(workspace_id=ws)
    s2 = Scope(workspace_id=ws, client_id=client, project_id=uuid4())
    print(f"  s1 = {s1}")
    print(f"  s2 = {s2}")

    print("\n── HDBSCANClusterer.assign — empty centroid set → (None, None)")

    class _MockHDBSCAN(HDBSCANClusterer):
        """Replace _compute_centroids so we don't need a real DB."""

        def __init__(self, centroids, **kw):
            super().__init__(**kw)
            self._mock = centroids

        def _compute_centroids(self, scope):
            return self._mock

    empty = _MockHDBSCAN(centroids={})
    cid, cname = empty.assign([0.1] * 384, s1)
    print(f"  result = ({cid}, {cname!r})  (no centroids → no assignment)")

    print("\n── HDBSCANClusterer.assign — two centroids → closest wins ──")
    cluster_a = uuid5(NAMESPACE_URL, "cluster-a")
    cluster_b = uuid5(NAMESPACE_URL, "cluster-b")
    vec_a = [1.0] + [0.0] * 383
    vec_b = [0.0] + [1.0] + [0.0] * 382
    populated = _MockHDBSCAN(centroids={
        cluster_a: (vec_a, "Topic A"),
        cluster_b: (vec_b, "Topic B"),
    })
    new = [0.9, 0.1] + [0.0] * 382  # similar to A
    cid, cname = populated.assign(new, s1)
    print(f"  closer-to-A embedding → ({cid}, {cname!r})  (expected: Topic A)")

    new = [0.1, 0.9] + [0.0] * 382  # similar to B
    cid, cname = populated.assign(new, s1)
    print(f"  closer-to-B embedding → ({cid}, {cname!r})  (expected: Topic B)")

    print("\n── HaikuNamer — construct only (real .name() needs LLM creds)")
    namer = HaikuNamer()
    print(f"  model = {namer._model}")
    print(f"  prompt prefix = {HaikuNamer.DEFAULT_PROMPT[:60]!r}...")

    print("\n── ClusteringService composition shape ──────────────────────")
    class _DummyEmbedder:
        def embed(self, text: str) -> list[float]:
            return new  # closer-to-B vector from above

    svc = ClusteringService(
        embedder=_DummyEmbedder(),
        clusterer=populated,
        namer=namer,
    )
    emb, cid, cname = svc.assign(body_md="hello world", scope=s1)
    print(f"  embedding[:3]={emb[:3]}  → cluster=({cid}, {cname!r})")
