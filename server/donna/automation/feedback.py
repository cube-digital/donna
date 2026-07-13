"""Plan 13 §7.3 — reaction → feedback polarity classifier.

The aggregator + this classifier are the *only* feedback-signal code in
v1: no ``FeedbackSignal`` model, no signal hook. We classify reactions
on read (here) and roll up per-(workspace, agent_session) win-rate on
the hourly aggregator (``tasks.feedback_aggregate``).

Keep ``POSITIVE_EMOJI`` and ``NEGATIVE_EMOJI`` as the single source of
truth — both the aggregator and any read-side caller share these sets.
"""
from __future__ import annotations

POSITIVE_EMOJI = frozenset({
    "👍", "✅", "❤️", "🎉", "💯",
    "+1", "thumbsup", "white_check_mark",
})
NEGATIVE_EMOJI = frozenset({
    "👎", "❌", "😡", "💩",
    "-1", "thumbsdown",
})


def polarity(emoji: str | None) -> str | None:
    """Return ``"positive"`` / ``"negative"`` / ``None``.

    ``None`` means "ignored" — emojis we don't classify, plus the
    explicit ``None`` input from rows that lost their emoji column.
    """
    if not emoji:
        return None
    if emoji in POSITIVE_EMOJI:
        return "positive"
    if emoji in NEGATIVE_EMOJI:
        return "negative"
    return None
