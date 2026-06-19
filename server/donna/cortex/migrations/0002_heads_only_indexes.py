"""Phase 1 heads-only partial indexes (2026-06-15).

The cortex read path is heads-only — superseded rows are invisible
to retrieval (R1). Postgres partial indexes on
``superseded_by IS NULL`` shrink the working set on every query;
without them the planner scans full-table for type+time + scope lookups.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("cortex", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="cortexentity",
            index=models.Index(
                fields=["workspace", "type", "-occurred_at"],
                condition=Q(superseded_by__isnull=True),
                name="cortex_heads_type_time",
            ),
        ),
        migrations.AddIndex(
            model_name="cortexentity",
            index=models.Index(
                fields=["workspace", "client_id", "project_id"],
                condition=Q(superseded_by__isnull=True),
                name="cortex_heads_scope",
            ),
        ),
        migrations.AddIndex(
            model_name="cortexentity",
            index=models.Index(
                fields=["workspace", "source"],
                condition=Q(superseded_by__isnull=True),
                name="cortex_heads_source",
            ),
        ),
    ]
