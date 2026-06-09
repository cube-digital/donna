"""
Initial Cortex migration — aligned with **Cortex Universal Silver
Specification v1 (rev 3)**.

Creates:

- ``vector`` Postgres extension (idempotent).
- ``cortex_entities`` table backing :class:`donna.cortex.models.CortexEntity`.
- BTREE indexes on (workspace, type, -occurred_at) + scope (workspace, client_id, project_id).
- GIN index on ``entity_refs`` JSONB column.
- IVFFLAT index on ``doc_embedding`` with cosine ops.
- Unique constraint on ``(workspace_id, content_hash)``.

Per spec §14, this Postgres index is **derived** — rebuilds from
``SilverStorage`` files at any time. Schema mirrors ``SilverEntity``
for cheap query plans.
"""
from __future__ import annotations

import uuid

import django.db.models.deletion
from django.core.files.storage import default_storage
from django.db import migrations, models
from pgvector.django import VectorField


def _body_upload_path(instance, filename):
    """Mirror of ``donna.cortex.models._body_upload_path`` — inlined here so
    the migration is self-contained at apply time."""
    return f"cortex/{instance.workspace_id}/{instance.type}/{instance.id}.md"


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="CortexEntity",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("meeting", "Meeting"),
                            ("email", "Email"),
                            ("chat", "Chat"),
                            ("doc", "Document"),
                            ("ticket", "Ticket"),
                            ("clip", "Web clip"),
                            ("note", "Note"),
                            ("person", "Person"),
                            ("org", "Organisation"),
                            ("project", "Project"),
                            ("concept", "Concept"),
                            ("decision", "Decision (ADR)"),
                        ],
                        max_length=16,
                        verbose_name="type",
                    ),
                ),
                (
                    "author",
                    models.CharField(
                        choices=[
                            ("donna", "Donna"),
                            ("human", "Human"),
                            ("agent", "Agent"),
                        ],
                        default="donna",
                        max_length=8,
                        verbose_name="author",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        help_text=(
                            "Provenance URI — e.g. fathom://meeting/<id>, "
                            "gmail://thread/<id>, manual://, cortex://synth/<run>."
                        ),
                        max_length=512,
                        verbose_name="source URI",
                    ),
                ),
                (
                    "bronze_storage_key",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Pointer to raw bronze blob in default_storage.",
                        max_length=500,
                        verbose_name="bronze storage key",
                    ),
                ),
                (
                    "content_hash",
                    models.CharField(
                        help_text="sha256(body_md). Drives idempotency.",
                        max_length=64,
                        verbose_name="content hash",
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(
                        help_text="When the source event happened.",
                        verbose_name="occurred at",
                    ),
                ),
                (
                    "client_id",
                    models.UUIDField(
                        blank=True,
                        db_index=True,
                        help_text="UUID of the client `org` row. NULL = workspace-owner content.",
                        null=True,
                        verbose_name="client id",
                    ),
                ),
                (
                    "project_id",
                    models.UUIDField(
                        blank=True,
                        db_index=True,
                        help_text="UUID of the `project` row. NULL only if client_id is also NULL.",
                        null=True,
                        verbose_name="project id",
                    ),
                ),
                (
                    "cluster_id",
                    models.UUIDField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="cluster id",
                    ),
                ),
                (
                    "doc_embedding",
                    VectorField(
                        blank=True,
                        dimensions=384,
                        help_text="BGE-small 384-dim embedding.",
                        null=True,
                        verbose_name="doc embedding",
                    ),
                ),
                (
                    "confidence",
                    models.CharField(
                        choices=[
                            ("high", "High"),
                            ("medium", "Medium"),
                            ("low", "Low"),
                        ],
                        default="high",
                        max_length=8,
                        verbose_name="confidence",
                    ),
                ),
                (
                    "last_synthesized",
                    models.DateField(
                        blank=True,
                        help_text=(
                            "Date this entity was last (re)synthesised. Drives "
                            "confidence decay (R8) and resynth triggers (R6)."
                        ),
                        null=True,
                        verbose_name="last synthesized",
                    ),
                ),
                ("title", models.CharField(max_length=500, verbose_name="title")),
                (
                    "body",
                    models.FileField(
                        blank=True,
                        help_text=(
                            "Rendered markdown body stored in SilverStorage. "
                            "Verbatim source content + Source: footer. Read "
                            "via `load_body()`."
                        ),
                        max_length=500,
                        storage=default_storage,
                        upload_to=_body_upload_path,
                        verbose_name="body markdown",
                    ),
                ),
                (
                    "body_byte_size",
                    models.IntegerField(
                        default=0,
                        help_text=(
                            "Cheap byte-size stat; avoids opening the file."
                        ),
                        verbose_name="body byte size",
                    ),
                ),
                (
                    "entity_refs",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="UUIDs of curated entities mentioned.",
                        verbose_name="entity refs",
                    ),
                ),
                (
                    "sources",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="UUIDs of entities that informed this one.",
                        verbose_name="sources",
                    ),
                ),
                (
                    "cross_refs",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Related entities in the same (workspace, client, project) scope.",
                        verbose_name="cross refs",
                    ),
                ),
                (
                    "supersedes",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Explicit replacement chain (same type).",
                        verbose_name="supersedes",
                    ),
                ),
                (
                    "parent",
                    models.UUIDField(
                        blank=True,
                        db_index=True,
                        help_text="Parent entity id (e.g. email from thread, clip from meeting).",
                        null=True,
                        verbose_name="parent",
                    ),
                ),
                (
                    "related",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Curated-to-curated cross-link only.",
                        verbose_name="related",
                    ),
                ),
                (
                    "applied_in",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="UUIDs of entities citing this one (reverse of sources).",
                        verbose_name="applied in",
                    ),
                ),
                (
                    "superseded_by",
                    models.UUIDField(
                        blank=True,
                        help_text="Newer entity that replaced this (reverse of supersedes).",
                        null=True,
                        verbose_name="superseded by",
                    ),
                ),
                (
                    "contradicts",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="Linter-detected conflicting entities (auto-populated).",
                        verbose_name="contradicts",
                    ),
                ),
                (
                    "extensions",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Per-type Pydantic-validated extension dict.",
                        verbose_name="extensions",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cortex_entities",
                        related_query_name="cortex_entity",
                        to="workspaces.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cortex entity",
                "verbose_name_plural": "Cortex entities",
                "db_table": "cortex_entities",
                "ordering": ["-occurred_at", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="cortexentity",
            constraint=models.UniqueConstraint(
                fields=["workspace", "content_hash"],
                name="uq_cortex_entity_ws_hash",
            ),
        ),
        migrations.AddIndex(
            model_name="cortexentity",
            index=models.Index(
                fields=["workspace", "type", "-occurred_at"],
                name="cortex_entity_type_time",
            ),
        ),
        migrations.AddIndex(
            model_name="cortexentity",
            index=models.Index(
                fields=["workspace", "client_id", "project_id"],
                name="cortex_entity_scope",
            ),
        ),
        # GIN on edge JSONB arrays + IVFFLAT on embedding can't be
        # expressed cleanly via Meta.indexes for these access patterns.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS cortex_entity_entity_refs_gin "
                "ON cortex_entities USING GIN (entity_refs); "
                "CREATE INDEX IF NOT EXISTS cortex_entity_extensions_gin "
                "ON cortex_entities USING GIN (extensions); "
                "CREATE INDEX IF NOT EXISTS cortex_entity_doc_emb_ivf "
                "ON cortex_entities USING ivfflat "
                "(doc_embedding vector_cosine_ops) WITH (lists = 100);"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS cortex_entity_entity_refs_gin; "
                "DROP INDEX IF EXISTS cortex_entity_extensions_gin; "
                "DROP INDEX IF EXISTS cortex_entity_doc_emb_ivf;"
            ),
        ),
    ]
