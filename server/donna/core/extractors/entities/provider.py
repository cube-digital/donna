"""ProviderMetadataExtractor — deterministic extraction from adapter metadata.

Surfaces ``person`` and ``org`` candidates from connector metadata
fields (host / sender / owner / participants / recipients / attendees).
Public email domains (gmail.com, …) are filtered from org spawns.
"""
from __future__ import annotations

from .base import EntityExtractor, ExtractContext, ExtractedEntity


_PUBLIC_EMAIL_DOMAINS: set[str] = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
    "live.com",
    "msn.com",
    "aol.com",
}


class ProviderMetadataExtractor(EntityExtractor):
    """Deterministic extraction from ``adapter.metadata()`` payload."""

    def extract(
        self, *, entity, context: ExtractContext
    ) -> list[ExtractedEntity]:
        meta = context.adapter_metadata or {}
        out: list[ExtractedEntity] = []

        for source in ("host", "sender", "owner"):
            obj = meta.get(source)
            if isinstance(obj, dict) and obj.get("email"):
                out.append(self._person(obj))

        for source in ("participants", "recipients", "to", "cc", "attendees"):
            for item in meta.get(source) or []:
                if isinstance(item, dict) and item.get("email"):
                    out.append(self._person(item))
                elif isinstance(item, str) and "@" in item:
                    out.append(self._person({"email": item, "name": item}))

        seen_domains: set[str] = set()
        for cand in list(out):
            if cand.email and "@" in cand.email:
                domain = cand.email.split("@", 1)[1].lower()
                if domain in _PUBLIC_EMAIL_DOMAINS:
                    continue
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)
                out.append(
                    ExtractedEntity(
                        type="org",
                        label=domain.split(".")[0].capitalize(),
                        email=None,
                        domain=domain,
                        confidence=0.9,
                        span=None,
                        origin="provider",
                    )
                )

        return out

    @staticmethod
    def _person(obj: dict) -> ExtractedEntity:
        return ExtractedEntity(
            type="person",
            label=obj.get("name") or obj.get("email"),
            email=(obj.get("email") or "").lower() or None,
            domain=None,
            confidence=1.0,
            span=None,
            origin="provider",
        )
