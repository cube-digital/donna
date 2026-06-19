"""
Embeddings — Subsystem 2 part 1.

Default ``BGESmallEmbedder`` uses ``BAAI/bge-small-en-v1.5`` (local,
384-dim). Heavy deps (sentence-transformers, torch) are lazy-imported
so the Django process doesn't pay the cost at import time, and
deployments that don't run the embed path don't need them.

Swap with ``OpenAIEmbedder`` (or any Protocol-conforming class) per
workspace by injecting at the ``CortexPipeline`` boundary.

Sampling helpers
----------------

BGE-small max context = 512 tokens ≈ ~1900 chars EN. We do NOT send
full bodies to the embedder for long content — instead each TypeSpec
declares an ``embedding_sampler`` that returns a representative window
within the budget. Spec §5 + the P0.14 plan in
``server/plans/cortex/06 - status/04-p0.14-...md`` describe the
rationale (anti-truncation: contracts have signatures at the end,
meetings carry decisions late, etc.).

Four samplers ship:

- ``fixed_window_sampler`` (default) — title + intro + middle + tail
- ``head_heavy_sampler`` — for chats / emails / tickets (latest first)
- ``head_tail_sampler`` — for ``doc`` types (intro + signatures)
- ``uniform_sampler`` — for meetings / runbooks (content distributed)
"""
from __future__ import annotations

from typing import Callable, Protocol


MAX_EMBED_CHARS = 1900


Sampler = Callable[[str, str], str]


# ── Samplers ────────────────────────────────────────────────────────


def fixed_window_sampler(title: str, body_md: str, max_chars: int = MAX_EMBED_CHARS) -> str:
    """Default. title + intro + middle + tail window mix.

    Spends the BGE-small token budget on the four most informative
    regions of the document. Short bodies pass through unchanged.
    """
    head = f"{title}\n\n" if title else ""
    if len(body_md) + len(head) <= max_chars:
        return f"{head}{body_md}"

    sep = "\n[...]\n"  # 8 chars × 2 separators = 16
    budget = max_chars - len(head) - 2 * len(sep)
    intro_len = int(budget * 0.40)
    mid_len = int(budget * 0.30)
    tail_len = budget - intro_len - mid_len

    intro = body_md[:intro_len]
    mid_start = max(0, len(body_md) // 2 - mid_len // 2)
    mid = body_md[mid_start : mid_start + mid_len]
    tail = body_md[-tail_len:]
    return f"{head}{intro}{sep}{mid}{sep}{tail}"


def head_heavy_sampler(
    title: str,
    body_md: str,
    max_chars: int = MAX_EMBED_CHARS,
    head_pct: float = 0.7,
    mid_pct: float = 0.2,
    tail_pct: float = 0.1,
) -> str:
    """Head-weighted window — for chats, emails, tickets.

    Latest reply / issue summary usually surfaces at the top of the
    rendered markdown.
    """
    head_marker = f"{title}\n\n" if title else ""
    if len(body_md) + len(head_marker) <= max_chars:
        return f"{head_marker}{body_md}"

    sep = "\n[...]\n"
    sep_count = 1 if tail_pct <= 0 else 2
    budget = max_chars - len(head_marker) - sep_count * len(sep)
    head_len = int(budget * head_pct)
    mid_len = int(budget * mid_pct)
    tail_len = budget - head_len - mid_len

    intro = body_md[:head_len]
    mid_start = max(0, len(body_md) // 2 - mid_len // 2)
    mid = body_md[mid_start : mid_start + mid_len]
    tail = body_md[-tail_len:] if tail_len > 0 else ""
    parts = [head_marker, intro, sep, mid]
    if tail:
        parts.extend([sep, tail])
    return "".join(parts)


def head_tail_sampler(
    title: str,
    body_md: str,
    max_chars: int = MAX_EMBED_CHARS,
    head_pct: float = 0.4,
    tail_pct: float = 0.6,
) -> str:
    """Intro + tail; skip the middle.

    Best for ``doc`` types — contracts (signatures at the end),
    plans (open questions at the end), ADRs (consequences at the end).
    """
    head_marker = f"{title}\n\n" if title else ""
    if len(body_md) + len(head_marker) <= max_chars:
        return f"{head_marker}{body_md}"

    sep = "\n[...]\n"
    budget = max_chars - len(head_marker) - len(sep)
    head_len = int(budget * head_pct)
    tail_len = budget - head_len

    intro = body_md[:head_len]
    tail = body_md[-tail_len:]
    return f"{head_marker}{intro}{sep}{tail}"


def uniform_sampler(
    title: str,
    body_md: str,
    max_chars: int = MAX_EMBED_CHARS,
    windows: int = 4,
) -> str:
    """Evenly-spaced windows across the body.

    Best for meetings (decisions distributed) and runbooks (steps in
    sequence).
    """
    head_marker = f"{title}\n\n" if title else ""
    if len(body_md) + len(head_marker) <= max_chars:
        return f"{head_marker}{body_md}"

    sep = "\n[...]\n"
    budget = max_chars - len(head_marker) - len(sep) * (windows - 1)
    window_len = budget // windows

    chunks: list[str] = []
    stride = max(1, (len(body_md) - window_len) // (windows - 1))
    for i in range(windows):
        start = min(i * stride, len(body_md) - window_len)
        chunks.append(body_md[start : start + window_len])
    return head_marker + sep.join(chunks)


# ── Protocol ────────────────────────────────────────────────────────


class EmbeddingStrategy(Protocol):
    """Embed text into a fixed-dim vector."""

    def embed(self, text: str) -> list[float]: ...

    def embed_entity(
        self,
        title: str,
        body_md: str,
        sampler: Sampler | None = ...,
    ) -> list[float]: ...


# ── BGE-small ───────────────────────────────────────────────────────


class BGESmallEmbedder:
    """384-dim embeddings via ``BAAI/bge-small-en-v1.5``."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        normalize: bool = True,
    ) -> None:
        self._model_name = model_name
        self._normalize = normalize
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "BGESmallEmbedder requires sentence-transformers. "
                    "Install with `uv add sentence-transformers`."
                ) from exc
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        vec = model.encode(
            text,
            normalize_embeddings=self._normalize,
            convert_to_numpy=True,
        )
        return vec.tolist()

    def embed_entity(
        self,
        title: str,
        body_md: str,
        sampler: Sampler | None = None,
    ) -> list[float]:
        """Embed an entity by applying a per-type sampler first.

        Args:
            title: Entity title (model column, separate from body).
            body_md: Raw markdown body (post-OCR / post-adapter, NOT
                the rendered output — the embedder sees content only).
            sampler: TypeSpec-specified sampler. ``None`` → default
                ``fixed_window_sampler``.
        """
        sampler = sampler or fixed_window_sampler
        text = sampler(title, body_md)
        return self.embed(text)


if __name__ == "__main__":
    # Run: `python -m donna.cortex.embeddings` (from `server/`)
    # Pure-Python sampler demos. Real embed() call is gated by
    # sentence-transformers availability.

    title = "Q4 Planning Meeting"
    short_body = "Short body that fits under the budget."
    # Build a long body so we can see windowing in action.
    long_body = (
        "INTRO. " * 200
        + "MIDDLE-MARKER. " * 200
        + "TAIL-SIGNATURES. " * 200
    )
    print(f"long_body length = {len(long_body)} chars (budget {MAX_EMBED_CHARS})")

    def show(name: str, out: str) -> None:
        print(f"\n── {name} ──  out len={len(out)}")
        print(out[:180] + ("…" if len(out) > 180 else ""))
        print("…")
        print(out[-180:])

    show("fixed_window_sampler (short — passthrough)", fixed_window_sampler(title, short_body))
    show("fixed_window_sampler (long)", fixed_window_sampler(title, long_body))
    show("head_heavy_sampler (long, chat/email/ticket)", head_heavy_sampler(title, long_body))
    show("head_tail_sampler (long, doc)", head_tail_sampler(title, long_body))
    show("uniform_sampler (long, meeting/runbook)", uniform_sampler(title, long_body))

    print("\n── BGESmallEmbedder.embed() (real call) ─────────────────────")
    embedder = BGESmallEmbedder()
    try:
        vec = embedder.embed("hello world")
        print(f"  OK: dim={len(vec)}  head={vec[:4]}")
    except ImportError as exc:
        print(f"  SKIPPED — {exc}")
    except Exception as exc:  # noqa: BLE001 — surface any model-loader fail
        print(f"  FAIL — {type(exc).__name__}: {exc}")
