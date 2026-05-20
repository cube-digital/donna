"""
integrations_bootstrap — seed OAuthProvider rows from connector class defaults.

Run on every deploy (idempotent). For each registered connector, ensures an
``OAuthProvider`` row exists with the connector's static defaults
(``default_authorize_url``, ``default_token_url``, ``default_scopes``).

Multiple connectors sharing the same ``oauth_provider_slug`` collapse to one
row with the union of their scopes — that's how multi-product vendors
(Google = Gmail + Drive + Calendar) get a single OAuth app.

Credentials (``client_id``/``client_secret``/``redirect_uri``) and the
``is_enabled`` flag are owned by the admin and set via Django admin. This
command **never** touches them on existing rows; on new rows it creates a
stub with empty credentials and ``is_enabled=False``.
"""
from __future__ import annotations

from typing import Iterable

from django.core.management.base import BaseCommand

from donna.core.integrations import all_loaded


class Command(BaseCommand):
    help = "Seed OAuthProvider rows from registered connector defaults."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without writing to the database.",
        )

    def handle(self, *args, dry_run: bool = False, **options):
        from donna.authentication.models import OAuthProvider

        connectors = all_loaded()
        if not connectors:
            self.stdout.write(self.style.WARNING(
                "No connectors registered. Nothing to bootstrap."
            ))
            return

        # Group by oauth_provider_slug — multi-product vendors collapse here.
        grouped: dict[str, list] = {}
        for cls in connectors:
            grouped.setdefault(cls.oauth_provider_slug, []).append(cls)

        for oauth_slug, classes in sorted(grouped.items()):
            scopes = sorted({s for cls in classes for s in (cls.default_scopes or [])})
            authorize_url = classes[0].default_authorize_url
            token_url = classes[0].default_token_url
            display_name = _common_prefix(c.display_name for c in classes) or oauth_slug.title()

            # Fields the connector class owns — always synced from code.
            connector_fields = {
                "display_name":   display_name,
                "authorize_url":  authorize_url,
                "token_url":      token_url,
                "default_scopes": scopes,
            }

            if dry_run:
                self.stdout.write(
                    f"would upsert OAuthProvider(slug={oauth_slug!r}): {connector_fields}"
                )
                continue

            existing = OAuthProvider.objects.filter(slug=oauth_slug).first()

            if existing is None:
                # Initial stub — empty credentials, disabled. Admin fills via
                # Django admin and flips is_enabled=True.
                OAuthProvider.objects.create(
                    slug=oauth_slug,
                    is_enabled=False,
                    **connector_fields,
                )
                action = "created"
                scope_status = "disabled (admin must fill credentials)"
            else:
                # Sync connector-owned metadata only — leave credentials +
                # is_enabled untouched.
                for k, v in connector_fields.items():
                    setattr(existing, k, v)
                existing.save(update_fields=list(connector_fields.keys()))
                action = "updated"
                scope_status = "enabled" if existing.is_enabled else "disabled"

            self.stdout.write(self.style.SUCCESS(
                f"{action} OAuthProvider(slug={oauth_slug!r}) → {scope_status} "
                f"({len(scopes)} scope(s), backs {len(classes)} connector(s))"
            ))


def _common_prefix(strings: Iterable[str]) -> str:
    """Longest common prefix of an iterable of strings, trimmed of trailing spaces."""
    strings = list(strings)
    if not strings:
        return ""
    if len(strings) == 1:
        return strings[0]
    head = strings[0]
    for other in strings[1:]:
        limit = min(len(head), len(other))
        i = 0
        while i < limit and head[i] == other[i]:
            i += 1
        head = head[:i]
        if not head:
            break
    return head.rstrip()
