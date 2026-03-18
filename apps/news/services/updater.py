import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import requests
from django.db import IntegrityError

from apps.news.models import Article, ArticleChunk, Feed

from .chunker import chunk_text
from .embeddings import BATCH_SIZE, MODEL, EmbeddingClient

logger = logging.getLogger(__name__)

TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; Newspaper/0.1)"
MAX_WORKERS = 20


def _fetch_single_feed(feed_id, url, title):
    """Fetch and parse a single RSS feed. Runs in a thread."""
    try:
        resp = requests.get(
            url, timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return feed_id, parsed.entries, None
    except Exception as e:
        return feed_id, [], f"{title}: {e}"


@dataclass
class UpdateResult:
    feeds_fetched: int = 0
    new_articles: int = 0
    fetch_errors: list[str] = field(default_factory=list)
    articles_embedded: int = 0
    chunks_created: int = 0
    total_tokens: int = 0


class FeedFetcher:
    """Fetch articles from all enabled RSS feeds."""

    def __init__(self, workers: int = MAX_WORKERS, stdout=None):
        self.workers = workers
        self.stdout = stdout

    def _write(self, msg: str):
        if self.stdout:
            self.stdout.write(msg)

    def fetch_all(self) -> tuple[int, int, list[str]]:
        """Fetch all enabled feeds. Returns (feeds_count, new_articles, errors)."""
        feeds = list(Feed.objects.filter(enabled=True))
        if not feeds:
            return 0, 0, []

        self._write(f"Fetching {len(feeds)} feeds...\n")
        total_new = 0
        errors = []

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_fetch_single_feed, f.id, f.url, f.title): f
                for f in feeds
            }

            for future in as_completed(futures):
                feed = futures[future]
                feed_id, entries, error = future.result()

                if error:
                    errors.append(error)
                    continue

                new_count = 0
                for entry in entries:
                    title = getattr(entry, "title", "") or ""
                    link = getattr(entry, "link", "") or ""
                    if not link:
                        continue

                    content = ""
                    if hasattr(entry, "content") and entry.content:
                        content = entry.content[0].get("value", "")
                    elif hasattr(entry, "summary"):
                        content = entry.summary or ""

                    published = None
                    for date_field in ("published_parsed", "updated_parsed"):
                        parsed_time = getattr(entry, date_field, None)
                        if parsed_time:
                            try:
                                published = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                            except (ValueError, TypeError):
                                pass
                            break

                    try:
                        Article.objects.create(
                            feed_id=feed_id,
                            title=title[:1000],
                            url=link[:2000],
                            content=content,
                            published=published,
                        )
                        new_count += 1
                    except IntegrityError:
                        pass

                total_new += new_count
                feed.last_fetched = datetime.now(timezone.utc)
                feed.save(update_fields=["last_fetched"])

        self._write(f"Done: {total_new} new articles\n")
        return len(feeds), total_new, errors


class ArticleEmbedder:
    """Embed unembedded articles: chunk → embed → save."""

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

        # Group chunks by article so we can mark each article done individually
        article_chunks = {}  # {article_id: [(chunk_index, chunk_text)]}
        for article_id, title, content in articles:
            chunks = chunk_text(title, content)
            article_chunks[article_id] = [
                (idx, text) for idx, text in enumerate(chunks)
            ]

        total_chunk_count = sum(len(v) for v in article_chunks.values())
        self._write(
            f"Embedding {len(articles)} articles ({total_chunk_count} chunks)...\n"
        )

        total_tokens = 0
        total_chunks_saved = 0
        articles_done = 0

        # Process one article at a time — save chunks and mark embedded immediately
        for article_id, chunks in article_chunks.items():
            texts = [text for _, text in chunks]

            # Embed all chunks for this article (may need multiple batches)
            all_embeddings = []
            for i in range(0, len(texts), BATCH_SIZE):
                batch_texts = texts[i:i + BATCH_SIZE]
                embeddings, tokens = client.embed_batch(batch_texts)
                all_embeddings.extend(embeddings)
                total_tokens += tokens

            # Save chunks to DB
            chunk_objects = []
            for (chunk_index, text), emb in zip(chunks, all_embeddings):
                chunk_objects.append(
                    ArticleChunk(
                        article_id=article_id,
                        chunk_index=chunk_index,
                        chunk_text=text,
                        embedding=EmbeddingClient.embedding_to_bytes(emb),
                        model=MODEL,
                    )
                )
            ArticleChunk.objects.bulk_create(chunk_objects, ignore_conflicts=True)

            # Mark this article as embedded right away
            Article.objects.filter(id=article_id).update(embedded=True)

            articles_done += 1
            total_chunks_saved += len(chunk_objects)

            if articles_done % 50 == 0 or articles_done == len(articles):
                self._write(
                    f"  {articles_done}/{len(articles)} articles embedded\n"
                )

        self._write(
            f"Done: {articles_done} articles, "
            f"{total_chunks_saved} chunks, {total_tokens} tokens\n"
        )
        return articles_done, total_chunks_saved, total_tokens


class UpdateService:
    """Orchestrator: fetch feeds then embed new articles."""

    def __init__(self, workers: int = MAX_WORKERS, api_key=None, stdout=None):
        self.fetcher = FeedFetcher(workers=workers, stdout=stdout)
        self.embedder = ArticleEmbedder(api_key=api_key, stdout=stdout)
        self.stdout = stdout

    def run(self, skip_embed: bool = False) -> UpdateResult:
        result = UpdateResult()

        feeds_count, new_articles, errors = self.fetcher.fetch_all()
        result.feeds_fetched = feeds_count
        result.new_articles = new_articles
        result.fetch_errors = errors

        if not skip_embed:
            articles, chunks, tokens = self.embedder.embed_new()
            result.articles_embedded = articles
            result.chunks_created = chunks
            result.total_tokens = tokens

        return result
