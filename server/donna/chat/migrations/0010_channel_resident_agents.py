"""Plan 13 §5.2.2 — channel-resident named agents.

Adds the discriminator + handle to ``AgentSession`` and a partial
``UniqueConstraint`` so two installs can't both own the same handle in
one channel. Existing rows default to non-resident.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_session_memory"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="is_channel_resident",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="resident_handle",
            field=models.SlugField(blank=True, default="", max_length=40),
        ),
        migrations.AddConstraint(
            model_name="agentsession",
            constraint=models.UniqueConstraint(
                fields=["channel", "resident_handle"],
                condition=models.Q(("is_channel_resident", True)),
                name="uniq_resident_agent_per_channel",
            ),
        ),
    ]
