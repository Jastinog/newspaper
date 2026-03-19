from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0016_topicembedding'),
    ]

    operations = [
        # Remove freshness from DigestSection, fix ordering
        migrations.RemoveField(
            model_name='digestsection',
            name='freshness',
        ),
        migrations.AlterModelOptions(
            name='digestsection',
            options={'ordering': ['order']},
        ),
        # Add freshness to DigestItem, sort by it
        migrations.AddField(
            model_name='digestitem',
            name='freshness',
            field=models.FloatField(default=0, db_index=True),
        ),
        migrations.AlterModelOptions(
            name='digestitem',
            options={'ordering': ['-freshness', 'order']},
        ),
    ]
