from django.db import migrations, models
import django.db.models.deletion
import pgvector.django


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0017_move_freshness_to_item'),
    ]

    operations = [
        # 1. Create DigestTopic model
        migrations.CreateModel(
            name='DigestTopic',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_en', models.CharField(max_length=200)),
                ('name_ru', models.CharField(blank=True, default='', max_length=200)),
                ('name_uk', models.CharField(blank=True, default='', max_length=200)),
                ('order', models.PositiveIntegerField(default=0)),
                ('enabled', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['order'],
            },
        ),
        # 2. Drop old TopicEmbedding entirely and recreate with FK
        migrations.DeleteModel(
            name='TopicEmbedding',
        ),
        migrations.CreateModel(
            name='TopicEmbedding',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.TextField(help_text='Search query describing this angle of the topic')),
                ('embedding', pgvector.django.VectorField(blank=True, dimensions=1536, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('topic', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='embeddings', to='news.digesttopic')),
            ],
            options={
                'ordering': ['topic__order'],
            },
        ),
    ]
