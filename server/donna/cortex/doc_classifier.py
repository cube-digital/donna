"""doc_type classification ladder — tier A heuristic (2026-06-14).

Two more tiers ship later:
- **B** (kNN over pgvector head embeddings) — 00f Phase 4.
- **B+** (TF-IDF + LogReg per-workspace) — 00f Phase 6.
- **C** (Haiku LLM) — already in template_engine.HaikuFitter.

Tier A is free, deterministic, fires on the obvious 40-60% of docs:
- MIME type mapping (pptx → presentation, …).
- Filename regex (NDA / contract / SOW / runbook / spec / …).
- Body anchor regex (WHEREAS / IN WITNESS WHEREOF → contract; …).

Every hit is a Haiku call that never happens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    doc_type: str | None
    confidence: float
    basis: str          # "mime" | "filename" | "anchor"


_MIME_MAP: dict[str, str] = {
    "application/vnd.ms-powerpoint": "presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "presentation",
    "application/vnd.google-apps.presentation": "presentation",
}

# (compiled regex, doc_type) — first match wins.
_FILENAME_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(nda|non[._\s-]?disclosure)\b", re.I), "contract"),
    (re.compile(r"\b(contract|agreement|sow|statement[._\s-]?of[._\s-]?work|msa)\b", re.I), "contract"),
    (re.compile(r"\b(offer|proposal)\b", re.I), "offer"),
    (re.compile(r"\b(invoice|po[._\s-]?\d+)\b", re.I), "other"),
    (re.compile(r"\b(runbook|playbook)\b", re.I), "runbook"),
    (re.compile(r"\b(spec|specification|design[._\s-]?doc|rfc)\b", re.I), "spec"),
    (re.compile(r"\b(adr|architecture[._\s-]?decision)\b", re.I), "decision"),
    (re.compile(r"\b(meeting[._\s-]?notes|minutes|standup)\b", re.I), "meeting_notes"),
    (re.compile(r"\b(report|quarterly|annual)\b", re.I), "report"),
    (re.compile(r"\b(readme)\b", re.I), "readme"),
]

# (compiled regex, doc_type, confidence). Anchors run against the
# head+tail of the body — cheap and bounded.
_BODY_ANCHORS: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"\bWHEREAS\b.*\bIN WITNESS WHEREOF\b", re.S), "contract", 0.95),
    (re.compile(r"\bAGREEMENT\b.*\bSignature\b", re.S | re.I), "contract", 0.75),
    (re.compile(r"\bRevision History\b.*\bTable of Contents\b", re.S | re.I), "spec", 0.80),
    (re.compile(r"^#+\s*Runbook\b", re.M | re.I), "runbook", 0.85),
    (re.compile(r"^#+\s*Architecture Decision\b", re.M | re.I), "decision", 0.85),
    (re.compile(r"^#+\s*Meeting Notes\b", re.M | re.I), "meeting_notes", 0.80),
]


class HeuristicDocClassifier:
    """Tier A — MIME → filename → body anchors. Fast, deterministic."""

    HEAD_CHARS = 4000
    TAIL_CHARS = 2000

    def classify(
        self,
        *,
        filename: str = "",
        mime: str = "",
        body_md: str = "",
    ) -> Classification:
        if mime in _MIME_MAP:
            return Classification(_MIME_MAP[mime], 0.95, "mime")

        for rx, dt in _FILENAME_SIGNALS:
            if rx.search(filename or ""):
                return Classification(dt, 0.85, "filename")

        sample = (body_md or "")[: self.HEAD_CHARS] + (body_md or "")[-self.TAIL_CHARS :]
        for rx, dt, conf in _BODY_ANCHORS:
            if rx.search(sample):
                return Classification(dt, conf, "anchor")

        return Classification(None, 0.0, "anchor")


# ── Tier B — kNN over pgvector head embeddings (Phase 4c, 2026-06-15) ─


class KNNDocClassifier:
    """Tier B — k-nearest-neighbour vote over labeled doc embeddings.

    For each unclassified doc: embed it, find the K nearest labeled
    docs in the same workspace, take the plurality ``doc_type``. If
    the winner exceeds ``min_vote_ratio``, return it; otherwise return
    None and the caller escalates to Haiku (tier C, in pipeline step 4).

    Pure-pgvector — no extra index needed beyond the existing
    ``doc_embedding`` column.
    """

    def __init__(
        self,
        embedder=None,
        k: int = 5,
        min_vote_ratio: float = 0.6,
    ) -> None:
        self._embedder = embedder
        self._k = k
        self._min_vote_ratio = min_vote_ratio

    def classify(
        self,
        *,
        workspace_id,
        title: str,
        body_md: str,
    ) -> Classification:
        try:
            from pgvector.django import CosineDistance
        except ImportError:
            return Classification(None, 0.0, "knn")
        if self._embedder is None:
            from donna.cortex.embeddings import BGESmallEmbedder
            self._embedder = BGESmallEmbedder()
        from donna.cortex.models import CortexEntity

        try:
            query_vec = self._embedder.embed_entity(
                title=title or "Untitled", body_md=body_md
            )
        except Exception:  # noqa: BLE001
            return Classification(None, 0.0, "knn")

        rows = list(
            CortexEntity.objects
            .filter(
                workspace_id=workspace_id,
                type="doc",
                superseded_by__isnull=True,
                doc_embedding__isnull=False,
                extensions__doc_type__isnull=False,
            )
            .exclude(extensions__doc_type="other")
            .annotate(_dist=CosineDistance("doc_embedding", query_vec))
            .order_by("_dist")
            .values("extensions", "_dist")[: self._k]
        )
        if not rows:
            return Classification(None, 0.0, "knn")

        votes: dict[str, int] = {}
        for r in rows:
            dt = (r["extensions"] or {}).get("doc_type")
            if dt:
                votes[dt] = votes.get(dt, 0) + 1
        if not votes:
            return Classification(None, 0.0, "knn")
        winner, count = max(votes.items(), key=lambda kv: kv[1])
        ratio = count / len(rows)
        if ratio < self._min_vote_ratio:
            return Classification(None, ratio, "knn")
        return Classification(winner, ratio, "knn")


if __name__ == "__main__":
    # Run: `python -m donna.cortex.doc_classifier` (from `server/`)
    clf = HeuristicDocClassifier()

    cases = [
        ("MIME pptx", dict(mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")),
        ("Filename NDA", dict(filename="Acme-NDA-2026.pdf")),
        ("Filename SOW", dict(filename="MSA-statement_of_work-v3.docx")),
        ("Filename runbook", dict(filename="oncall-runbook.md")),
        ("Body WHEREAS contract", dict(body_md="WHEREAS the parties agree…\n…\nIN WITNESS WHEREOF the parties hereto…")),
        ("Body runbook heading", dict(body_md="# Runbook: restart everything\n\nSteps:\n1. drain\n2. restart")),
        ("Nothing matches", dict(filename="notes.txt", body_md="hello world")),
    ]
    for label, kw in cases:
        result = clf.classify(**kw)
        print(f"  {label:<35} → {result}")
