"""
``manage.py cortex_sync`` smoke tests.

Heavy operations (BGE-small model load, HDBSCAN, LLM cluster naming)
are off the test path — we exercise the command's argument plumbing,
workspace resolution, and dry-run paths.
"""
from __future__ import annotations

import io
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from donna.cortex.models import CortexEntity
from donna.workspaces.models import Workspace


class CortexSyncCommandTests(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}"
        )

    def test_no_flag_errors(self) -> None:
        with self.assertRaises(CommandError):
            call_command("cortex_sync")

    def test_rebuild_flag_blocked(self) -> None:
        with self.assertRaises(CommandError):
            call_command("cortex_sync", "--rebuild")

    def test_workspace_resolution_by_slug(self) -> None:
        # Empty workspace + dry-run reindex prints "would_update: 0"
        out = io.StringIO()
        call_command(
            "cortex_sync",
            "--reindex-embeddings",
            "--workspace",
            self.workspace.slug,
            "--dry-run",
            stdout=out,
        )
        self.assertIn("would_update", out.getvalue())

    def test_workspace_resolution_by_uuid(self) -> None:
        out = io.StringIO()
        call_command(
            "cortex_sync",
            "--reindex-embeddings",
            "--workspace",
            str(self.workspace.id),
            "--dry-run",
            stdout=out,
        )
        self.assertIn("would_update", out.getvalue())

    def test_workspace_unknown_errors(self) -> None:
        with self.assertRaises(CommandError):
            call_command(
                "cortex_sync",
                "--reindex-embeddings",
                "--workspace",
                "does-not-exist",
            )

    def test_rebuild_clusters_dry_run(self) -> None:
        out = io.StringIO()
        call_command(
            "cortex_sync",
            "--rebuild-clusters",
            "--workspace",
            self.workspace.slug,
            "--dry-run",
            stdout=out,
        )
        self.assertIn("would_recluster_workspaces", out.getvalue())
