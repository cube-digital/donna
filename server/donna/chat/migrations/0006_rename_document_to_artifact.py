# Rename chat.Document → chat.Artifact (model + db table). Data preserved.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_channelpin_messagereaction_message_mention_flags_and_more'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Document',
            new_name='Artifact',
        ),
        migrations.AlterModelTable(
            name='artifact',
            table='artifacts',
        ),
    ]
