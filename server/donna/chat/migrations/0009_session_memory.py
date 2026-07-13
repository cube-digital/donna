"""Plan 13 §4.1 + §4.4 — SessionMemory model.

Per-turn extracted notes with relationship sharding. Indexes cover the
two hot paths: per-session reads and cross-session ``(scope, scope_ref)``
lookups.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0008_message_hil_question_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SessionMemory",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False,
                        primary_key=True, serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("turn_id", models.CharField(max_length=40)),
                (
                    "scope",
                    models.CharField(
                        choices=[
                            ("user", "user"),
                            ("channel", "channel"),
                            ("peer", "peer"),
                            ("project", "project"),
                            ("org", "org"),
                            ("self", "self"),
                        ],
                        default="user",
                        max_length=16,
                    ),
                ),
                ("scope_ref", models.CharField(blank=True, default="", max_length=80)),
                ("body", models.TextField()),
                ("confidence", models.FloatField(default=0.7)),
                ("consolidated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memory_entries",
                        to="chat.agentsession",
                    ),
                ),
            ],
            options={
                "db_table": "chat_session_memory",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="sessionmemory",
            index=models.Index(
                fields=["session", "scope"], name="chat_sessio_session_b80c63_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sessionmemory",
            index=models.Index(
                fields=["scope", "scope_ref"], name="chat_sessio_scope_2bb1a2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sessionmemory",
            index=models.Index(
                condition=models.Q(("consolidated_at__isnull", True)),
                fields=["consolidated_at"],
                name="sessionmem_pending_idx",
            ),
        ),
    ]
