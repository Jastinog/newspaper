import logging
from dataclasses import dataclass, field

from apps.news.models import Article, ArticleChunk

from .chunker import chunk_text
from .embeddings import BATCH_SIZE, MODEL, EmbeddingClient
from .extractor import ContentExtractor
from .fetcher import FeedFetcher

logger = logging.getLogger(__name__)

MAX_WORKERS = 20


@dataclass
class UpdateResult:
    feeds_fetched: int = 0
    new_articles: int = 0
    fetch_errors: list[str] = field(default_factory=list)
    articles_extracted: int = 0
    extract_errors: list[str] = field(default_factory=list)
    articles_embedded: int = 0
    chunks_created: int = 0
    total_tokens: int = 0


class ArticleEmbedder:
    """Embed unembedded articles: chunk -> embed -> save.

    Processes one article at a time, saving progress immediately.
    """

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
            Article.objects.filter(embedded=False)
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
                # Embed all chunks for this article
                all_embeddings = []
                for i in range(0, len(chunks), BATCH_SIZE):
                    batch_texts = chunks[i:i + BATCH_SIZE]
                    embeddings, tokens = client.embed_batch(batch_texts)
                    all_embeddings.extend(embeddings)
                    total_tokens += tokens
            except Exception as e:
                logger.warning("Embed failed for article %s: %s", article_id, e)
                skipped += 1
                # Mark embedded to avoid retrying broken articles
                Article.objects.filter(id=article_id).update(embedded=True)
                continue

            # Save chunks to DB
            chunk_objects = [
                ArticleChunk(
                    article_id=article_id,
                    chunk_index=idx,
                    chunk_text=text,
                    embedding=EmbeddingClient.embedding_to_bytes(emb),
                    model=MODEL,
                )
                for idx, (text, emb) in enumerate(zip(chunks, all_embeddings))
            ]
            ArticleChunk.objects.bulk_create(chunk_objects, ignore_conflicts=True)

            # Mark embedded immediately
            Article.objects.filter(id=article_id).update(embedded=True)

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


class UpdateService:
    """Orchestrator: fetch RSS -> extract content -> embed.

    Pipeline:
      1. FeedFetcher     — download RSS, create Article records
      2. ContentExtractor — fetch full text from URLs via readability
      3. ArticleEmbedder  — chunk text, get embeddings, save
    """

    def __init__(self, workers: int = MAX_WORKERS, days: int = 30, api_key=None, stdout=None):
        self.fetcher = FeedFetcher(workers=workers, stdout=stdout)
        self.extractor = ContentExtractor(workers=workers, days=days, stdout=stdout)
        self.embedder = ArticleEmbedder(api_key=api_key, stdout=stdout)
        self.stdout = stdout

    def run(
        self,
        skip_extract: bool = False,
        skip_embed: bool = False,
    ) -> UpdateResult:
        result = UpdateResult()

        # Step 1: Fetch RSS feeds
        feeds_count, new_articles, errors = self.fetcher.fetch_all()
        result.feeds_fetched = feeds_count
        result.new_articles = new_articles
        result.fetch_errors = errors

        # Step 2: Extract full content from URLs
        if not skip_extract:
            total, extracted, ext_errors = self.extractor.extract_new()
            result.articles_extracted = extracted
            result.extract_errors = ext_errors

        # Step 3: Embed articles
        if not skip_embed:
            articles, chunks, tokens = self.embedder.embed_new()
            result.articles_embedded = articles
            result.chunks_created = chunks
            result.total_tokens = tokens

        return result
