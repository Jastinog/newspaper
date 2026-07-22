"""Embed a single article and persist its chunk vectors."""

import logging

from django.db import transaction

from apps.feed.models import ArticleChunk

from apps.feed.services.inference import client as inference

from .chunker import chunk_article
from .embedder import MODEL_NAME, LocalEmbedder

logger = logging.getLogger(__name__)


def embed_article(article_id: int, title: str, content: str = "") -> int:
    """Chunk one article, embed every chunk with the local model, and store the
    ArticleChunk rows.

    Returns the number of chunks stored. Replaces any existing chunks for the
    article, so it is safe to re-run. Raises if the embedder can't run — the
    caller decides how to handle a model failure (the harvester stage swallows
    it so the pipeline never stalls)."""
    chunks = chunk_article(title, content)
    if not chunks:
        return 0

    if inference.remote_enabled():
        vectors = inference.embed(chunks, is_query=False)
    else:
        vectors = [v.tolist() for v in LocalEmbedder.instance().embed(chunks, is_query=False)]

    rows = [
        ArticleChunk(
            article_id=article_id,
            chunk_index=i,
            chunk_text=text,
            embedding=vectors[i],
            model=MODEL_NAME,
        )
        for i, text in enumerate(chunks)
    ]

    with transaction.atomic():
        ArticleChunk.objects.filter(article_id=article_id).delete()
        ArticleChunk.objects.bulk_create(rows)

    return len(rows)
