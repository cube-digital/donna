"""Plan 13 §7.1 — Schedule model migration."""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("chat", "0011_artifact_metadata"),
        ("workspaces", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Schedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("cron", models.CharField(max_length=80)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("enabled", models.BooleanField(default=True)),
                ("last_fired_at", models.DateTimeField(blank=True, null=True)),
                ("next_fires_at", models.DateTimeField(blank=True, null=True)),
                (
                    "agent_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedules",
                        to="chat.agentsession",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedules",
                        to="workspaces.workspace",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "automation_schedule"},
        ),
        migrations.AddIndex(
            model_name="schedule",
            index=models.Index(fields=["enabled", "next_fires_at"], name="automation__enabled_e87b94_idx"),
        ),
        migrations.AddIndex(
            model_name="schedule",
            index=models.Index(fields=["agent_session"], name="automation__agent_s_2c84a3_idx"),
        ),
    ]
