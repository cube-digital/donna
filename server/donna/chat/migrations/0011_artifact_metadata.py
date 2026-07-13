"""Plan 13 §6.1 + §6.3 — Artifact.metadata JSONField.

Holds MagicDocs sibling-artifact pointers (``status_artifact_id``) and
multi-audience grouping (``audience``).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_channel_resident_agents"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifact",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
