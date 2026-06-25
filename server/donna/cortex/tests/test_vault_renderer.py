"""
Phase 5 vault renderer tests.

Runs with ``InMemoryStorage`` (auto-injected in settings when tests
detected) so nothing escapes to the host filesystem. CORTEX_VAULT_ENABLED
is also auto-disabled during tests; the cases that exercise the vault
hook itself ``@override_settings`` to flip it back on.

Coverage matrix (from plan B5):
- render_entity writes at parent_path
- frontmatter augmentation injects id + content_hash
- parse_frontmatter round-trips a rendered entity
- _index.md lists heads only (excludes superseded)
- _log.md append is order-preserving
- rebuild from vault recreates rows by id (round-trip)
- post-commit hook fires only when CORTEX_VAULT_ENABLED
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings

from donna.cortex.models import CortexEntity
from donna.cortex.vault_renderer import (
    VaultRenderer,
    _augment_frontmatter,
    parse_frontmatter,
    vault_root_for,
)
from donna.workspaces.models import Workspace


# ── helpers ────────────────────────────────────────────────────────────


def _make_entity(
    workspace: Workspace,
    *,
    parent_path: str = "emails/2026/05",
    slug: str = "2026-05-20-test",
    type: str = "email",
    title: str = "Test Email",
    content_hash: str | None = None,
    body_md: str = "---\ntype: email\ntitle: Test Email\n---\n\n# Test Email\n\nBody.",
) -> CortexEntity:
    # Auto-vary content_hash by slug — DB constraint requires uniqueness
    # per (workspace, content_hash).
    if content_hash is None:
        import hashlib
        content_hash = hashlib.sha256(slug.encode()).hexdigest()
    entity = CortexEntity(
        id=uuid.uuid4(),
        workspace=workspace,
        type=type,
        title=title,
        author="donna",
        occurred_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        source=f"test://email/{slug}",
        content_hash=content_hash,
        extensions={"parent_path": parent_path, "slug": slug},
    )
    entity.body.save(
        name=f"{entity.id}.md",
        content=ContentFile(body_md.encode()),
        save=False,
    )
    entity.save()
    return entity


# ── tests ──────────────────────────────────────────────────────────────


class FrontmatterAugmentTests(TestCase):
    """Pure-function tests — no Django storage involved."""

    def test_injects_missing_keys(self) -> None:
        body = b"---\ntype: email\ntitle: x\n---\n\n# x"
        out = _augment_frontmatter(body, id="abc-123", content_hash="dead")
        decoded = out.decode()
        self.assertIn("id: abc-123", decoded)
        self.assertIn("content_hash: dead", decoded)
        self.assertIn("---\ntype: email", decoded)

    def test_skips_keys_already_present(self) -> None:
        body = b"---\nid: keep-me\n---\n\nbody"
        out = _augment_frontmatter(body, id="should-not-overwrite")
        self.assertIn("id: keep-me", out.decode())
        self.assertNotIn("should-not-overwrite", out.decode())

    def test_no_frontmatter_prepends_one(self) -> None:
        body = b"# Plain markdown body"
        out = _augment_frontmatter(body, id="abc")
        decoded = out.decode()
        self.assertTrue(decoded.startswith("---\n"))
        self.assertIn("id: abc", decoded)


class ParseFrontmatterTests(TestCase):
    def test_extracts_known_scalars(self) -> None:
        body = b"---\ntype: email\nid: abc-123\ncontent_hash: dead\nslug: my-slug\n---\nbody"
        fm, rest = parse_frontmatter(body)
        self.assertEqual(fm["type"], "email")
        self.assertEqual(fm["id"], "abc-123")
        self.assertEqual(fm["content_hash"], "dead")
        self.assertEqual(fm["slug"], "my-slug")
        self.assertEqual(rest, "body")

    def test_survives_jinja_template_inlining_bug(self) -> None:
        # Real-world rendered output has malformed YAML where a value
        # runs straight into the next key (no newline). parse_frontmatter
        # must extract both fields.
        body = (
            b"---\n"
            b"type: email\n"
            b"occurred_at: 2026-05-27 12:21:30+00:00parent_path: emails/2026/05\n"
            b"slug: 2026-05-27-foo\n"
            b"---\nbody"
        )
        fm, _ = parse_frontmatter(body)
        self.assertEqual(fm["occurred_at"], "2026-05-27 12:21:30+00:00")
        self.assertEqual(fm["parent_path"], "emails/2026/05")
        self.assertEqual(fm["slug"], "2026-05-27-foo")


@override_settings(CORTEX_VAULT_ENABLED=True)
class VaultRendererTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Test", slug=f"test-{uuid.uuid4().hex[:8]}"
        )
        self.renderer = VaultRenderer()

    def test_render_entity_writes_at_parent_path(self) -> None:
        ent = _make_entity(self.workspace)
        path = self.renderer.render_entity(ent)
        expected = (
            f"{vault_root_for(self.workspace.id)}/"
            f"emails/2026/05/2026-05-20-test.md"
        )
        self.assertEqual(path, expected)
        self.assertTrue(default_storage.exists(expected))

    def test_render_entity_augments_frontmatter_with_id(self) -> None:
        ent = _make_entity(self.workspace)
        path = self.renderer.render_entity(ent)
        with default_storage.open(path) as f:
            written = f.read().decode()
        self.assertIn(f"id: {ent.id}", written)
        self.assertIn(f"content_hash: {ent.content_hash}", written)

    def test_render_entity_missing_slug_skipped(self) -> None:
        ent = _make_entity(self.workspace)
        ent.extensions = {"parent_path": "emails/2026/05"}  # no slug
        ent.save()
        self.assertIsNone(self.renderer.render_entity(ent))

    def test_render_index_lists_heads_only(self) -> None:
        head = _make_entity(self.workspace, slug="head-slug")
        superseded = _make_entity(self.workspace, slug="superseded-slug")
        superseded.superseded_by = head.id
        superseded.save(update_fields=["superseded_by"])

        path = self.renderer.render_index(self.workspace.id, "emails/2026/05")
        with default_storage.open(path) as f:
            index = f.read().decode()
        self.assertIn("head-slug", index)
        self.assertNotIn("superseded-slug", index)

    def test_append_log_preserves_order(self) -> None:
        path1 = self.renderer.append_log(
            self.workspace.id, "clients/acme",
            {"type": "email", "id": "1", "action": "saved"},
        )
        path2 = self.renderer.append_log(
            self.workspace.id, "clients/acme",
            {"type": "email", "id": "2", "action": "saved"},
        )
        self.assertEqual(path1, path2)
        with default_storage.open(path1) as f:
            content = f.read().decode()
        lines = [ln for ln in content.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("email | 1 | saved", lines[0])
        self.assertIn("email | 2 | saved", lines[1])

    def test_disabled_when_flag_off(self) -> None:
        ent = _make_entity(self.workspace)
        with override_settings(CORTEX_VAULT_ENABLED=False):
            result = self.renderer.render_entity(ent)
        self.assertIsNone(result)


@override_settings(CORTEX_VAULT_ENABLED=True)
class RebuildRoundTripTests(TestCase):
    """End-to-end: render → wipe row → cortex_sync --rebuild → row back."""

    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="RT", slug=f"rt-{uuid.uuid4().hex[:8]}"
        )

    def test_rebuild_recreates_wiped_entity(self) -> None:
        from django.core.management import call_command

        ent = _make_entity(self.workspace, slug="round-trip-slug")
        renderer = VaultRenderer()
        renderer.render_entity(ent)

        # Wipe the row — vault file remains.
        original_id = ent.id
        original_title = ent.title
        original_hash = ent.content_hash
        ent.delete()
        self.assertFalse(
            CortexEntity.objects.filter(id=original_id).exists()
        )

        # Rebuild walks vault → recreates row by id.
        call_command(
            "cortex_sync", "--rebuild",
            "--workspace", self.workspace.slug,
        )

        restored = CortexEntity.objects.filter(id=original_id).first()
        self.assertIsNotNone(restored)
        self.assertEqual(restored.title, original_title)
        self.assertEqual(restored.content_hash, original_hash)
        self.assertEqual(restored.type, "email")
