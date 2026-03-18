"""Migrate ArticleChunk.embedding from BinaryField to pgvector VectorField.

Steps:
1. Enable pgvector extension
2. Add new vector column
3. Convert binary data -> vector
4. Drop old binary column & rename new one
5. Add HNSW index for cosine search
"""

import struct

from django.db import migrations
from pgvector.django import HnswIndex, VectorField


def binary_to_vector(apps, schema_editor):
    """Convert packed float32 bytes to pgvector vectors."""
    ArticleChunk = apps.get_model("news", "ArticleChunk")
    batch = []
    for chunk in ArticleChunk.objects.only("id", "embedding").iterator(chunk_size=500):
        raw = bytes(chunk.embedding)
        count = len(raw) // 4
        floats = list(struct.unpack(f"<{count}f", raw))
        chunk.embedding_vec = floats
        batch.append(chunk)
        if len(batch) >= 500:
            ArticleChunk.objects.bulk_update(batch, ["embedding_vec"])
            batch = []
    if batch:
        ArticleChunk.objects.bulk_update(batch, ["embedding_vec"])


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0010_api_usage"),
    ]

    operations = [
        # 1. Enable pgvector extension
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;",
        ),
        # 2. Add new vector column (nullable during migration)
        migrations.AddField(
            model_name="articlechunk",
            name="embedding_vec",
            field=VectorField(dimensions=1536, null=True),
        ),
        # 3. Copy binary data -> vector
        migrations.RunPython(binary_to_vector, migrations.RunPython.noop),
        # 4. Drop old binary column
        migrations.RemoveField(
            model_name="articlechunk",
            name="embedding",
        ),
        # 5. Rename new column to 'embedding'
        migrations.RenameField(
            model_name="articlechunk",
            old_name="embedding_vec",
            new_name="embedding",
        ),
        # 6. Make non-nullable
        migrations.AlterField(
            model_name="articlechunk",
            name="embedding",
            field=VectorField(dimensions=1536),
        ),
        # 7. Add HNSW index for fast cosine similarity search
        migrations.AddIndex(
            model_name="articlechunk",
            index=HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ),
    ]
