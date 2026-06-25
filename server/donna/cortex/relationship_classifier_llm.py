"""
Tier B — Haiku-judged relationship classifier.

Fires for orgs Tier A (rules) couldn't decide. Reads org metadata +
small email-history sample, asks Haiku for a structured verdict.

Cost: ~$0.001-0.005 per org (input ~2KB, output ~150 tokens). 24 orgs
in cube-digital ≈ $0.05 total — well below the eval-gate threshold.

Returns ``Classification`` (same dataclass as Tier A) so callers can
treat both tiers uniformly.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from donna.cortex.relationship_classifier import Classification, Relationship


logger = logging.getLogger(__name__)


_PROMPT = """\
You classify the relationship between OUR org (the workspace owner) and \
ONE external org, based on a few email excerpts.

Valid labels (closed enum, pick exactly one):

  client   = we bill / serve / deliver to them (paying engagements)
  partner  = we co-build / co-sell / refer with them; joint customers
  vendor   = we consume their service (SaaS, suppliers, airlines, hosting,
             travel, payment processors, CI/CD, communication tools)
  peer     = industry contact, prospect-in-conversation, non-transactional
  unknown  = signal too weak to decide; do NOT guess

Hard rules:
- Marketing emails / receipts / shipping confirmations → vendor
- Bidirectional human conversation + commercial intent (SoW,
  deliverables, milestones, invoices we SENT) → client
- "Co-build", "co-sell", "joint customer", "white-label", "revenue
  share" language → partner
- Bidirectional but only meeting invites / casual exchanges → peer
- < 3 emails total or unclear → unknown (do NOT guess)

Return ONLY a JSON object on a single line, no markdown fences:
{{"relationship": "...", "confidence": 0.0-1.0, "reasoning": "<one short sentence>"}}

---

ORG: {org_title}
Domains: {domains}
Inbound emails (they → us): {inbound}
Outbound emails (us → them): {outbound}
Distinct senders: {senders}

Email excerpts (titles + first 200 chars of body):
{excerpts}
"""


def classify_via_llm(
    *,
    org_title: str,
    org_domains: list[str],
    sender_emails: Iterable[str],
    inbound_count: int,
    outbound_count: int,
    body_samples: list[str],
    model: str = "anthropic/claude-haiku-4-5-20251001",
) -> Classification:
    """Run Haiku judge. Returns Classification.

    Falls back to ``unknown`` on any failure (network, parse, refusal).
    """
    senders_list = list(sender_emails)[:10]
    samples = list(body_samples)[:8]

    excerpts_text = "\n---\n".join(
        f"[{i + 1}] {s[:600]}"
        for i, s in enumerate(samples)
    ) or "(no samples available)"

    prompt = _PROMPT.format(
        org_title=org_title or "(unknown)",
        domains=", ".join(org_domains) or "(none)",
        inbound=inbound_count,
        outbound=outbound_count,
        senders=", ".join(senders_list) or "(none)",
        excerpts=excerpts_text,
    )

    try:
        from donna.core.llm.factory import LLMFactory

        provider = LLMFactory.create(model=model)
        response = provider.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "relationship_llm_call_failed",
            extra={"org_title": org_title, "error": str(exc)},
        )
        return Classification(
            relationship="unknown",
            confidence=0.0,
            basis="llm:failed",
            evidence=[f"LLM call error: {type(exc).__name__}"],
        )

    return _parse_verdict(raw, org_title=org_title)


_JSON_RE = re.compile(r"\{[^{}]*\"relationship\"[^{}]*\}", re.DOTALL)
_ALLOWED_LABELS = {"client", "partner", "vendor", "peer", "unknown"}


def _parse_verdict(raw: str, *, org_title: str) -> Classification:
    """Extract JSON from Haiku output. Reject anything outside the enum."""
    m = _JSON_RE.search(raw)
    if not m:
        logger.warning(
            "relationship_llm_parse_failed_no_json",
            extra={"org_title": org_title, "raw_preview": raw[:200]},
        )
        return Classification(
            relationship="unknown",
            confidence=0.0,
            basis="llm:parse_failed",
            evidence=[f"no JSON in response: {raw[:120]}"],
        )

    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning(
            "relationship_llm_parse_failed_invalid_json",
            extra={"org_title": org_title, "error": str(exc)},
        )
        return Classification(
            relationship="unknown",
            confidence=0.0,
            basis="llm:parse_failed",
            evidence=[f"invalid JSON: {exc}"],
        )

    label = str(data.get("relationship", "unknown")).strip().lower()
    if label not in _ALLOWED_LABELS:
        return Classification(
            relationship="unknown",
            confidence=0.0,
            basis="llm:invalid_label",
            evidence=[f"label '{label}' not in {sorted(_ALLOWED_LABELS)}"],
        )

    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    reasoning = str(data.get("reasoning", "")).strip()[:240]

    # Threshold: only apply if confidence >= 0.7 (per 00m §Tier B)
    if conf < 0.7 and label != "unknown":
        logger.info(
            "relationship_llm_low_confidence_demoted_to_unknown",
            extra={"org_title": org_title, "label": label, "conf": conf},
        )
        return Classification(
            relationship="unknown",
            confidence=conf,
            basis="llm:low_confidence",
            evidence=[f"haiku said '{label}' (conf={conf:.2f}, below 0.7 threshold)", reasoning],
        )

    return Classification(
        relationship=label,  # type: ignore[arg-type]
        confidence=conf,
        basis="llm:haiku",
        evidence=[reasoning] if reasoning else [],
    )
