import logging

from apps.billing.models import APIUsage
from django.utils import timezone

from apps.feed.models import Article, ArticleChunk, ArticlePipeline
from apps.core.services.ai import EMBEDDING_MODEL, EmbeddingClient, calculate_cost
from apps.core.services.ai.embeddings import BATCH_SIZE

from .chunker import chunk_text

logger = logging.getLogger(__name__)


class ArticleEmbedder:
    """Embed unembedded articles: chunk -> embed -> save."""

    def __init__(self, api_key=None, stdout=None):
        self.api_key = api_key
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def embed_new(self) -> tuple[int, int, int]:
        """Embed all unembedded articles. Returns (articles, chunks, tokens)."""
        client = EmbeddingClient(api_key=self.api_key)
        articles = list(
            Article.objects.filter(pipeline__embedded_at__isnull=True)
            .exclude(content="")
            .values_list("id", "title", "content")
        )

        if not articles:
            self._write("No articles to embed.\n")
            return 0, 0, 0

        self._write(f"Embedding {len(articles)} articles...\n")

        total_tokens = 0
        total_chunks_saved = 0
        articles_done = 0

        skipped = 0
        for article_id, title, content in articles:
            chunks = chunk_text(title, content)

            try:
                all_embeddings = []
                for i in range(0, len(chunks), BATCH_SIZE):
                    batch_texts = chunks[i:i + BATCH_SIZE]
                    embeddings, tokens = client.embed_batch(batch_texts)
                    all_embeddings.extend(embeddings)
                    total_tokens += tokens
                    APIUsage.objects.create(
                        service=APIUsage.Service.EMBEDDING,
                        api_type=APIUsage.APIType.EMBEDDING,
                        model=EMBEDDING_MODEL,
                        prompt_tokens=tokens,
                        completion_tokens=0,
                        total_tokens=tokens,
                        cost_usd=calculate_cost(EMBEDDING_MODEL, tokens),
                    )
            except Exception as e:
                logger.warning("Embed failed for article %s: %s", article_id, e)
                skipped += 1
                ArticlePipeline.objects.update_or_create(
                    article_id=article_id,
                    defaults={"embedded_at": timezone.now()},
                )
                continue

            chunk_objects = [
                ArticleChunk(
                    article_id=article_id,
                    chunk_index=idx,
                    chunk_text=text,
                    embedding=emb,
                    model=EMBEDDING_MODEL,
                )
                for idx, (text, emb) in enumerate(zip(chunks, all_embeddings))
            ]
            ArticleChunk.objects.bulk_create(chunk_objects, ignore_conflicts=True)

            ArticlePipeline.objects.update_or_create(
                article_id=article_id,
                defaults={"embedded_at": timezone.now()},
            )

            articles_done += 1
            total_chunks_saved += len(chunk_objects)

            if articles_done % 50 == 0 or articles_done == len(articles):
                self._write(
                    f"  {articles_done}/{len(articles)} articles embedded\n"
                )

        msg = f"Done: {articles_done} articles, {total_chunks_saved} chunks, {total_tokens} tokens"
        if skipped:
            msg += f" ({skipped} skipped)"
        self._write(msg + "\n")
        return articles_done, total_chunks_saved, total_tokens
