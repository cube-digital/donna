"""Plan 13 §1.3 + §1.5 — Message HIL question/answer fields.

Adds the discriminator + payload columns that let an agent suspend a
turn on a question, surface it in the channel, and resume when the user
posts an answer. The partial index covers the cleanup cron's hot path:
"every open (unanswered) question past its expiry."

The new fields are nullable / defaulted — no data migration required.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0007_agentsession_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="kind",
            field=models.CharField(
                choices=[
                    ("chat", "chat"),
                    ("question", "question"),
                    ("answer", "answer"),
                ],
                default="chat",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="question_options",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="message",
            name="answer_payload",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="answered_message",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="answers",
                to="chat.message",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                condition=models.Q(("kind", "question"), ("answer_payload__isnull", True)),
                fields=["channel", "kind", "expires_at"],
                name="msg_open_question_idx",
            ),
        ),
    ]
