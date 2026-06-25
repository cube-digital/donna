"""
Org relationship classifier — Tier A (rule-based, deterministic, free).

Spec: ``docs/important-docs/00m - org-relationship-taxonomy.md``.

The classifier runs at two moments:

  1. **At org spawn** (synchronous, in ``_spawn_org``) — uses whatever
     signals are available at that instant: the org's email_domains +
     the (single) email that triggered the spawn. Returns one of
     ``{self, vendor, unknown}`` with high precision but low recall —
     for ambiguous cases it returns ``unknown`` rather than guessing
     client.
  2. **Nightly batch + on-demand backfill** (``cortex_sync
     --reclassify-orgs``) — re-runs over the workspace's full email
     corpus. Direction asymmetry, vocabulary regex, and email volume
     all kick in here. Catches orgs whose first email looked
     ambiguous but the broader pattern now resolves.

Tier B (Haiku LLM judge) is a separate module that fires for orgs
Tier A leaves as ``unknown``.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Literal
from uuid import UUID


logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────


Relationship = Literal["self", "client", "partner", "vendor", "peer", "unknown"]


@dataclass(frozen=True)
class Classification:
    relationship: Relationship
    confidence: float          # 0.0 – 1.0
    basis: str                 # short tag: "rule:noreply" | "rule:allowlist" | …
    evidence: list[str] = field(default_factory=list)  # short audit bullets


# ── Tier A rules ──────────────────────────────────────────────────────


_NOREPLY_RE = re.compile(
    r"^(no[-_]?reply|do[-_]?not[-_]?reply|notifications?|alerts?|"
    r"billing|invoices?|receipts?|automated|news|noticias|info|"
    r"hello|team|reservations?|booking|support|customercare|"
    r"helpdesk)\b",
    re.IGNORECASE,
)

_VOCAB_VENDOR = re.compile(
    r"\b(invoice|receipt|payment\s+confirmation|order\s+confirmation|"
    r"booking|reservation|tracking\s+number|shipment|your\s+order|"
    r"itinerary|boarding\s+pass|e[-\s]?ticket)\b",
    re.IGNORECASE,
)
_VOCAB_CLIENT = re.compile(
    r"\b(milestone|deliverable|statement\s+of\s+work|SoW|scope\s+of\s+work|"
    r"engagement|retainer|contract\s+amendment|kickoff\s+meeting|"
    r"deliverables\s+due)\b",
    re.IGNORECASE,
)
_VOCAB_PARTNER = re.compile(
    r"\b(partnership|co[-\s]?(?:host|build|sell|market|develop)|"
    r"joint\s+(?:customer|client|engagement|webinar|event)|"
    r"reseller|referral\s+(?:fee|agreement)|"
    r"white[-\s]?label|revenue\s+share|"
    r"strategic\s+alliance)\b",
    re.IGNORECASE,
)


def classify_on_spawn(
    *,
    org_domain: str | None,
    workspace_primary_domain: str | None,
    first_sender_email: str | None = None,
) -> Classification:
    """Cheap synchronous classification at org-spawn time.

    Only fires rules that need a single email. Returns ``unknown``
    when no rule matches — the nightly batch fills in the rest.
    """
    evidence: list[str] = []

    # Rule 1: self
    if org_domain and workspace_primary_domain:
        if _root(org_domain) == _root(workspace_primary_domain):
            return Classification(
                relationship="self",
                confidence=1.0,
                basis="rule:self",
                evidence=[f"domain={org_domain} matches workspace primary"],
            )

    # Rule 2: noreply-pattern sender → vendor
    if first_sender_email and "@" in first_sender_email:
        local, _, _ = first_sender_email.partition("@")
        if _NOREPLY_RE.match(local):
            return Classification(
                relationship="vendor",
                confidence=0.85,
                basis="rule:noreply",
                evidence=[f"first sender local-part='{local}' matches automated pattern"],
            )

    # Rule 3: known-vendor allowlist
    if org_domain and _is_known_vendor(org_domain):
        return Classification(
            relationship="vendor",
            confidence=0.95,
            basis="rule:allowlist",
            evidence=[f"domain={org_domain} in curated vendor allowlist"],
        )

    # No rule fired — return unknown so the nightly batch can re-tier
    # with more signal (direction stats + vocab over all emails).
    return Classification(
        relationship="unknown",
        confidence=0.0,
        basis="",
        evidence=["no rule matched at spawn; deferred to batch classifier"],
    )


def classify_with_history(
    *,
    org_domain: str | None,
    workspace_primary_domain: str | None,
    sender_emails: Iterable[str],          # all distinct senders from this org
    inbound_count: int,                    # emails FROM this org → us
    outbound_count: int,                   # emails FROM us → this org's domain
    body_samples: Iterable[str],           # 3-10 short body excerpts (~500 chars each)
) -> Classification:
    """Full classification with workspace-level signal.

    Runs nightly + on-demand via ``cortex_sync --reclassify-orgs``.
    Picks the highest-confidence rule that fires; falls through to
    LLM Tier B (caller's responsibility) if nothing definitive.
    """
    evidence: list[str] = []

    # Rule 1: self (highest priority)
    if org_domain and workspace_primary_domain:
        if _root(org_domain) == _root(workspace_primary_domain):
            return Classification(
                relationship="self",
                confidence=1.0,
                basis="rule:self",
                evidence=[f"domain={org_domain} matches workspace primary"],
            )

    # Rule 2: known-vendor allowlist (very high precision)
    if org_domain and _is_known_vendor(org_domain):
        return Classification(
            relationship="vendor",
            confidence=0.95,
            basis="rule:allowlist",
            evidence=[f"domain={org_domain} in curated vendor allowlist"],
        )

    # Rule 3: every sender matches noreply pattern → vendor
    senders = list(sender_emails)
    if senders:
        noreply_hits = sum(
            1 for s in senders
            if "@" in s and _NOREPLY_RE.match(s.split("@", 1)[0])
        )
        if noreply_hits == len(senders):
            return Classification(
                relationship="vendor",
                confidence=0.9,
                basis="rule:noreply",
                evidence=[f"{noreply_hits}/{len(senders)} senders are automated"],
            )

    # Rule 4: direction asymmetry — heavy inbound, no outbound → vendor
    if inbound_count >= 3 and outbound_count == 0:
        return Classification(
            relationship="vendor",
            confidence=0.75,
            basis="rule:direction",
            evidence=[f"inbound={inbound_count}, outbound=0 (no human reply ever)"],
        )

    # Rule 5: vocabulary scoring (only if direction is balanced enough
    # to be a real relationship — i.e. some bidirectional traffic)
    if inbound_count > 0 and outbound_count > 0:
        combined = "\n".join(body_samples)
        v_score = len(_VOCAB_VENDOR.findall(combined))
        c_score = len(_VOCAB_CLIENT.findall(combined))
        p_score = len(_VOCAB_PARTNER.findall(combined))
        # Need clear winner: top score >= 3 AND >= 2× runner-up
        scores = sorted(
            [("vendor", v_score), ("client", c_score), ("partner", p_score)],
            key=lambda kv: -kv[1],
        )
        top, second = scores[0], scores[1]
        if top[1] >= 3 and top[1] >= 2 * max(second[1], 1):
            return Classification(
                relationship=top[0],          # type: ignore[arg-type]
                confidence=0.7,
                basis="rule:vocab",
                evidence=[
                    f"vocab scores: vendor={v_score} client={c_score} partner={p_score}"
                ],
            )

    # Rule 6: bidirectional + zero-vocab signal → peer (the default
    # bucket for "real human conversation but no commercial cues")
    if inbound_count > 0 and outbound_count > 0:
        return Classification(
            relationship="peer",
            confidence=0.5,
            basis="rule:bidirectional",
            evidence=[
                f"in={inbound_count} out={outbound_count}; no vocab signal — likely peer"
            ],
        )

    # Nothing definitive — leave for Tier B
    return Classification(
        relationship="unknown",
        confidence=0.0,
        basis="",
        evidence=["no Tier A rule fired with sufficient confidence"],
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _root(domain: str) -> str:
    """Reduce subdomain to the root for matching (e.g. m.x.com → x.com)."""
    domain = domain.lower().strip().lstrip("@")
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    # naive root: last 2 segments. Misses .co.uk / .com.au etc.; acceptable
    # for v1 since the allowlist is the high-precision arbiter.
    return ".".join(parts[-2:])


@lru_cache(maxsize=1)
def _vendor_set() -> frozenset[str]:
    path = Path(__file__).parent / "data" / "known_vendors.txt"
    if not path.exists():
        return frozenset()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line.lower())
    return frozenset(out)


def _is_known_vendor(domain: str) -> bool:
    s = _vendor_set()
    if not s:
        return False
    domain = domain.lower().strip().lstrip("@")
    if domain in s:
        return True
    # Try root-domain match (e.g. m.animawings.com → animawings.com)
    root = _root(domain)
    return root in s
