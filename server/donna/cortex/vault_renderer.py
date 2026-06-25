"""
Phase 5 — Vault Projection.

Renders the logical hierarchy stored as ``CortexEntity.extensions["parent_path"]``
into real directories on disk, so:

- Obsidian (or any file-tree viewer) can browse the workspace
- The agent can read a compressed scope index before searching
- The DB becomes derivable: ``cortex_sync --rebuild`` walks the vault
  and reconstructs Postgres (spec §14 promise, executable)

Layout
------
::

    vault/<workspace_id>/
      _index.md                       ← workspace-root overview
      _log.md                         ← append-only activity log
      people/<slug>.md
      concepts/<slug>.md
      clients/<slug>/
        org.md
        _index.md
        _log.md
        emails/YYYY/MM/<slug>.md
        meetings/YYYY/MM/<slug>.md
        docs/<slug>.md
        decisions/<slug>.md
        projects/<slug>/
          project.md
          _index.md
          emails/YYYY/MM/...
          docs/...

Entity body is rendered by the pipeline (Jinja template) and stored on
``CortexEntity.body`` (FileField) at the flat path
``cortex/<ws>/<type>/<id>.md``. Vault renderer **copies** that body to
``vault/<ws>/<parent_path>/<slug>.md`` so both surfaces coexist:

- Flat: id-addressable, never moves (scope changes are JSON-only)
- Vault: human-browsable, mutable as scope evolves

Append-immediate writes (entity + log) live in this module's synchronous
path; ``_index.md`` regeneration is debounced via a Redis dirty-set and
flushed by the ``flush_vault_indexes`` Celery beat task in ``tasks.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

if TYPE_CHECKING:
    from donna.cortex.models import CortexEntity

logger = logging.getLogger(__name__)


# ── Path computation ──────────────────────────────────────────────────


def vault_root_for(workspace_id) -> str:
    """Top-level vault directory for one workspace.

    Sibling to the flat ``cortex/`` tree; both live under ``default_storage``.
    """
    return f"vault/{workspace_id}"


_CANONICAL_FILENAMES = {
    "org":     "org",      # clients/<slug>/org.md
    "project": "project",  # clients/<c>/projects/<p>/project.md
}


def _entity_relative_path(entity: "CortexEntity") -> str | None:
    """Compute ``<parent_path>/<filename>.md`` relative to vault root.

    For org / project entities, the filename is the canonical
    ``org.md`` / ``project.md`` (the entity anchors its own folder).
    For every other type the slug becomes the filename.

    ``parent_path`` is **recomputed at render time** via the type's
    folder resolver — never trust the cached value on ``extensions``.
    This is what makes scope promotion (e.g. ``relationship`` flip
    from vendor → client) automatically re-file the entity on the next
    render without a separate reflow job.

    Returns None when the entity is missing required extensions
    (corrupted row; caller skips rendering and logs).
    """
    ext = entity.extensions or {}
    slug = ext.get("slug")
    if not slug:
        return None
    filename = _CANONICAL_FILENAMES.get(entity.type, slug)

    parent_path = _recompute_parent_path(entity)
    if parent_path:
        return f"{parent_path.strip('/')}/{filename}.md"
    return f"{filename}.md"


def _recompute_parent_path(entity: "CortexEntity") -> str:
    """Live-resolve ``parent_path`` via the type's folder resolver.

    Falls back to ``entity.extensions['parent_path']`` (the cached
    pipeline value) if the resolver lookup fails for any reason —
    keeps render best-effort.
    """
    ext = entity.extensions or {}
    try:
        from donna.cortex.clustering import Scope
        from donna.cortex.registry import TemplateRegistry
        from donna.cortex.scope import scope_slugs_for

        spec = TemplateRegistry().get(entity.type)
        scope = Scope(
            workspace_id=entity.workspace_id,
            client_id=entity.client_id,
            project_id=entity.project_id,
        )
        client_prefix, project_slug = scope_slugs_for(scope)
        return spec.folder_resolver(
            type=entity.type,
            occurred_at=entity.occurred_at,
            extensions=ext,
            client_slug=client_prefix,
            project_slug=project_slug,
        )
    except Exception:  # noqa: BLE001
        return ext.get("parent_path", "") or ""


def _entity_absolute_path(entity: "CortexEntity") -> str | None:
    rel = _entity_relative_path(entity)
    if rel is None:
        return None
    return f"{vault_root_for(entity.workspace_id)}/{rel}"


# ── Renderer ──────────────────────────────────────────────────────────


class VaultRenderer:
    """Stateless renderer. One instance is fine, but no state is held."""

    # — public surface used by callers (manager hook, beat task, command) —

    def render_entity(self, entity: "CortexEntity") -> str | None:
        """Write ``<vault_root>/<parent_path>/<slug>.md`` for one entity.

        Body content = the same rendered Jinja markdown that lives on
        ``entity.body`` (flat cortex tree). We read it via ``entity.body``
        (FileField) and write a copy at the hierarchical path.

        Returns the vault-relative path written (or None on skip).
        """
        if not getattr(settings, "CORTEX_VAULT_ENABLED", True):
            return None

        vault_path = _entity_absolute_path(entity)
        if vault_path is None:
            logger.warning(
                "vault_render_skip_missing_slug",
                extra={"entity_id": str(entity.id), "type": entity.type},
            )
            return None

        if not entity.body:
            logger.warning(
                "vault_render_skip_no_body",
                extra={"entity_id": str(entity.id), "type": entity.type},
            )
            return None

        entity.body.open("rb")
        try:
            body_bytes = entity.body.read()
        finally:
            entity.body.close()

        # Inject id + content_hash + source + (for orgs) relationship
        # truth into the existing frontmatter block so
        # ``cortex_sync --rebuild`` can reconstruct rows from files
        # alone. Pipeline-rendered bodies don't carry ``source``.
        # For ``org`` rows, the multi-label taxonomy
        # (relationship / roles / client_of / locked) lives ONLY in
        # extensions; vault is the durable store after a DB wipe.
        extras: dict[str, str] = {
            "id":           str(entity.id),
            "content_hash": entity.content_hash or "",
            "source":       entity.source or "",
        }
        if entity.type == "org":
            ext = entity.extensions or {}
            extras["relationship"] = ext.get("relationship", "unknown")
            roles = ext.get("roles") or []
            if roles:
                extras["roles"] = "|".join(roles)
            client_of = ext.get("client_of") or []
            if client_of:
                extras["client_of"] = "|".join(client_of)
            if ext.get("relationship_locked"):
                extras["relationship_locked"] = "true"
        body_bytes = _augment_frontmatter(body_bytes, **extras)

        # Overwrite-safe: delete-then-save (default_storage.save would
        # append a suffix to disambiguate, which we don't want — the
        # vault path is canonical).
        if default_storage.exists(vault_path):
            default_storage.delete(vault_path)
        default_storage.save(vault_path, ContentFile(body_bytes))
        return vault_path

    def render_index(self, workspace_id, folder_path: str) -> str:
        """Regenerate ``<vault_root>/<folder_path>/_index.md`` for one folder.

        Lists heads only (``superseded_by_id IS NULL``) under that exact
        ``parent_path``. Groups by type + a per-type sub-discriminator.

        Multi-label badges (00m, 2026-06-19): if the folder hosts a
        single org (``<bucket>/<slug>/``), the index also lists the
        org's extra ``roles[]`` and ``client_of[]`` org names so an
        Obsidian browser sees "Also a client" / "Client of weasweb"
        right at the top.
        """
        # Local import to avoid module-load circularity with models.py
        # bootstrapping the manager.
        from donna.cortex.models import CortexEntity

        heads = list(
            CortexEntity.objects
            .filter(
                workspace_id=workspace_id,
                superseded_by__isnull=True,
                extensions__parent_path=folder_path,
            )
            .order_by("type", "-occurred_at")
        )

        # Per-org badge line — picks the org row at this folder (if any).
        badge_lines = self._org_badge_lines(workspace_id, folder_path)

        lines: list[str] = [f"# {folder_path or '/'}", ""]
        lines.extend(badge_lines)
        if not heads:
            lines.append("_(empty folder)_")
        else:
            by_type: dict[str, list[CortexEntity]] = {}
            for ent in heads:
                by_type.setdefault(ent.type, []).append(ent)
            for type_name in sorted(by_type):
                items = by_type[type_name]
                lines.append(f"## {type_name.title()} ({len(items)})")
                for ent in items:
                    slug = (ent.extensions or {}).get("slug") or str(ent.id)
                    date_marker = ""
                    if ent.occurred_at:
                        try:
                            date_marker = f" — {ent.occurred_at:%Y-%m-%d}"
                        except Exception:  # noqa: BLE001
                            pass
                    lines.append(f"- [[{slug}]] — {ent.title}{date_marker}")
                lines.append("")
        lines.append(f"_Last updated: {_utc_now_iso()}_")

        path = f"{vault_root_for(workspace_id)}/{folder_path.strip('/')}/_index.md".rstrip("/")
        if not folder_path:
            path = f"{vault_root_for(workspace_id)}/_index.md"
        if default_storage.exists(path):
            default_storage.delete(path)
        default_storage.save(path, ContentFile("\n".join(lines).encode()))
        return path

    def _org_badge_lines(self, workspace_id, folder_path: str) -> list[str]:
        """Build the multi-role + client_of badge block for org folders.

        Returns empty list when the folder isn't an org's own folder
        (i.e. no org row sits at ``parent_path == folder_path``).
        """
        from donna.cortex.models import CortexEntity

        org = (
            CortexEntity.objects
            .filter(
                workspace_id=workspace_id,
                type="org",
                superseded_by__isnull=True,
                extensions__parent_path=folder_path,
            )
            .first()
        )
        if org is None:
            return []

        ext = org.extensions or {}
        primary = ext.get("relationship", "unknown")
        roles = [r for r in (ext.get("roles") or []) if r and r != primary]
        client_of_uuids = ext.get("client_of") or []

        lines: list[str] = []
        if roles:
            lines.append(f"**Also:** {', '.join(roles)}")
        if client_of_uuids:
            # Resolve UUIDs → org titles for human-readable badge
            partners = (
                CortexEntity.objects
                .filter(workspace_id=workspace_id, id__in=client_of_uuids)
                .values_list("title", flat=True)
            )
            partner_list = list(partners)
            if partner_list:
                lines.append(
                    f"**Client of:** {', '.join(f'[[{p}]]' for p in partner_list)}"
                )
        if lines:
            lines.append("")  # blank line before content
        return lines

    def append_log(self, workspace_id, scope_prefix: str, event: dict) -> str:
        """Append one event line to ``<vault_root>/<scope_prefix>/_log.md``.

        Event dict expected keys: ``type``, ``id``, ``action``. Format:
        ``<ts> | <type> | <id> | <action>``.
        """
        ts = _utc_now_iso()
        line = (
            f"{ts} | {event.get('type', '?')} | "
            f"{event.get('id', '?')} | {event.get('action', '?')}\n"
        )
        prefix = (scope_prefix or "").strip("/")
        path = f"{vault_root_for(workspace_id)}/{prefix}/_log.md" if prefix \
            else f"{vault_root_for(workspace_id)}/_log.md"

        if default_storage.exists(path):
            with default_storage.open(path, mode="rb") as f:
                existing = f.read()
            new_content = existing + line.encode()
            default_storage.delete(path)
            default_storage.save(path, ContentFile(new_content))
        else:
            default_storage.save(path, ContentFile(line.encode()))
        return path

    def render_index_for_prompt(
        self,
        workspace_id,
        scope: dict | None = None,
        max_chars: int = 2500,
    ) -> str:
        """Compressed scope index for injection into the agent system prompt.

        ``scope`` shape: ``{"client_slug": str|None, "project_slug": str|None}``.
        Prioritises recent items + decisions. Hard-capped at ``max_chars``.
        """
        from donna.cortex.models import CortexEntity

        qs = CortexEntity.objects.filter(
            workspace_id=workspace_id,
            superseded_by__isnull=True,
        )
        if scope:
            cs = scope.get("client_slug")
            ps = scope.get("project_slug")
            prefix = ""
            if cs and ps:
                prefix = f"clients/{cs}/projects/{ps}"
            elif cs:
                prefix = f"clients/{cs}"
            elif ps:
                prefix = f"projects/{ps}"
            if prefix:
                qs = qs.filter(extensions__parent_path__startswith=prefix)

        # Decisions first (always informative), then most-recent of others.
        decisions = list(qs.filter(type="decision").order_by("-occurred_at")[:20])
        others = list(qs.exclude(type="decision").order_by("-occurred_at")[:50])

        lines = ["## Workspace map (compressed)\n"]
        if decisions:
            lines.append(f"### Decisions ({len(decisions)})")
            for d in decisions:
                lines.append(f"- {d.title}")
            lines.append("")
        if others:
            by_type: dict[str, list[CortexEntity]] = {}
            for ent in others:
                by_type.setdefault(ent.type, []).append(ent)
            for type_name in sorted(by_type):
                items = by_type[type_name]
                lines.append(f"### {type_name.title()} ({len(items)})")
                for ent in items[:8]:  # cap per-type
                    date = f" ({ent.occurred_at:%Y-%m-%d})" if ent.occurred_at else ""
                    lines.append(f"- {ent.title}{date}")
                lines.append("")

        out = "\n".join(lines)
        if len(out) > max_chars:
            out = out[: max_chars - 20] + "\n…(truncated)"
        return out


# ── Helpers ────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _augment_frontmatter(body_bytes: bytes, **kvs: str) -> bytes:
    """Inject ``key: value`` lines into the existing ``---`` frontmatter
    block at the top of a rendered cortex body.

    Idempotent: if a key already appears in the frontmatter, the
    existing value is preserved (so a re-render of the same entity
    doesn't churn the file). If there is no frontmatter block,
    prepends one.
    """
    body = body_bytes.decode("utf-8", errors="replace")

    if not body.startswith("---"):
        # No frontmatter — prepend one with just the injected keys.
        lines = ["---"] + [f"{k}: {v}" for k, v in kvs.items() if v] + ["---", "", body]
        return "\n".join(lines).encode("utf-8")

    # Find the closing ``---`` of the frontmatter block.
    parts = body.split("\n")
    end_idx = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return body_bytes  # malformed; leave alone

    existing_keys = set()
    for line in parts[1:end_idx]:
        if ":" in line:
            existing_keys.add(line.split(":", 1)[0].strip())

    additions = [f"{k}: {v}" for k, v in kvs.items() if v and k not in existing_keys]
    if not additions:
        return body_bytes  # already has everything we'd add

    new_lines = parts[: end_idx] + additions + parts[end_idx:]
    return "\n".join(new_lines).encode("utf-8")


def parse_frontmatter(body_bytes: bytes) -> tuple[dict, str]:
    """Split a rendered cortex body into ``(frontmatter_dict, body_md_str)``.

    The current Jinja templates emit malformed YAML in places (e.g.
    ``occurred_at: 2026-05-27 12:21:30+00:00parent_path: emails/2026/05``
    on one line — missing newline). Rather than depend on PyYAML or
    sweep every template, we regex-extract the small set of known
    scalar keys we actually need for rebuild.
    """
    import re

    body = body_bytes.decode("utf-8", errors="replace")
    if not body.startswith("---"):
        return {}, body

    parts = body.split("\n")
    end_idx = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, body

    raw_block = "\n".join(parts[1:end_idx])

    # Known scalar fields we need for rebuild.
    fields = [
        "id", "content_hash", "type", "title", "occurred_at",
        "slug", "parent_path", "source", "author",
        "template_version", "cluster_name", "thread_id",
        # Org-relationship truth (00m). For non-org rows these are
        # absent and the regex simply doesn't match.
        "relationship", "roles", "client_of", "relationship_locked",
    ]
    # Build a lookahead pattern that ONLY matches a *known* field as the
    # next key. Naïve ``\w+:`` lookahead breaks on ``12:21:30+00:00``
    # (would split at ``21:``); restricting to known fields keeps
    # timestamps intact while still recovering merged-line cases like
    # ``occurred_at: 2026-05-27 12:21:30+00:00parent_path: emails/...``.
    next_key_alternation = "|".join(re.escape(f) for f in fields)

    fm: dict = {}
    for field in fields:
        # Field key may appear at start of line OR run-on after another
        # value with no whitespace (Jinja inlining bug — value like
        # ``2026-05-27 12:21:30+00:00parent_path: ...``). ``\b`` does
        # NOT match between digits and letters (both word chars), so we
        # use ``(?<![a-zA-Z_])`` to allow that boundary too.
        m = re.search(
            rf"(?<![a-zA-Z_]){re.escape(field)}:\s*(.*?)(?=\s*(?:{next_key_alternation}):|\n|$)",
            raw_block,
        )
        if m:
            value = m.group(1).strip().strip('"').strip("'")
            if value:
                fm[field] = value

    rest = "\n".join(parts[end_idx + 1:]).lstrip("\n")
    return fm, rest
