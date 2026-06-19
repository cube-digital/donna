"""Phase 2 — DeliveryPackage canonical_type + canonical_payload (2026-06-15).

Adds two columns so connectors can hand the cortex pipeline a
``CanonicalEntity``-shaped payload instead of a loose ``metadata`` dict.
Both default to blank/{}; existing rows are untouched.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0003_remove_clientcredentials_authorize_url_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliverypackage",
            name="canonical_type",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Cortex EntityType ('meeting'/'email'/'doc'/...) emitted by the adapter.",
                max_length=32,
                verbose_name="canonical type",
            ),
        ),
        migrations.AddField(
            model_name="deliverypackage",
            name="canonical_payload",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="CanonicalEntity.as_payload() — typed adapter output.",
                verbose_name="canonical payload",
            ),
        ),
    ]
