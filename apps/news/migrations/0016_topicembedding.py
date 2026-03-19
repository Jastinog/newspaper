from django.db import migrations, models
import pgvector.django


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0015_add_importance_to_digestitem'),
    ]

    operations = [
        migrations.CreateModel(
            name='TopicEmbedding',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('topic_index', models.PositiveIntegerField(db_index=True)),
                ('description', models.TextField()),
                ('embedding', pgvector.django.VectorField(dimensions=1536)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['topic_index'],
            },
        ),
    ]
