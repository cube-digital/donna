"""Plan 13 §2.1 — AgentSession.mode field.

Adds a per-session mode discriminator that gates which tools the agent
can use during a turn:

- ``chat``     : Q&A only (cortex reads).
- ``drafting`` : Q&A + draft mutations.
- ``planning`` : read-only rehearsal — Q&A + read_draft, no writes.

Existing rows default to ``chat``. The legacy ``config['draft_enabled']``
flag continues to work as a fallback inside ``build_registry``; rows
where the operator wants drafting permanently should set
``mode='drafting'`` rather than relying on the config shim.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_rename_document_to_artifact"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="mode",
            field=models.CharField(
                choices=[
                    ("chat", "chat"),
                    ("drafting", "drafting"),
                    ("planning", "planning"),
                ],
                default="chat",
                max_length=16,
            ),
        ),
    ]
