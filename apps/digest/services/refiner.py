import logging
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.core.services.ai import EmbeddingClient
from apps.feed.models import Article, ArticleChunk
from apps.digest.models import DigestConfig

logger = logging.getLogger(__name__)


def trim_content(text: str, max_length: int) -> str:
    """Trim text to max_length, breaking at sentence boundaries when possible."""
    if not text or len(text) <= max_length:
        return text or ""
    truncated = text[:max_length]
    # Try to break at last sentence boundary
    last_period = truncated.rfind('. ')
    if last_period > max_length * 0.6:
        return truncated[:last_period + 1]
    return truncated + "..."


class StoryRefiner:
    """Refines article collection for a specific story using LLM-generated search queries."""

    def __init__(self, embedder: EmbeddingClient = None, config: DigestConfig = None):
        self.embedder = embedder or EmbeddingClient()
        self.config = config or DigestConfig.get()

    def refine(self, story: dict, original_articles: dict) -> list[dict]:
        """Find best articles for a story using refined embedding search.

        Args:
            story: {"label": str, "article_ids": [int], "search_queries": [str]}
            original_articles: {article_id: article_dict} - all articles from collector

        Returns:
            List of article dicts with trimmed content, ready for generation.
        """
        cfg = self.config
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.hours_lookback)

        # Start with originally identified articles
        result_ids = set(story.get("article_ids", []))

        # Embed search queries and find additional articles
        queries = story.get("search_queries", [])
        if queries:
            try:
                vectors, _ = self.embedder.embed_batch(queries)
            except Exception as e:
                logger.warning("Failed to embed refine queries for '%s': %s", story.get("label"), e)
                vectors = []

            max_distance = 1.0 - cfg.similarity_threshold
            for emb in vectors:
                results = (
                    ArticleChunk.objects
                    .filter(article__published__gte=cutoff)
                    .annotate(distance=CosineDistance("embedding", emb))
                    .filter(distance__lte=max_distance)
                    .order_by("distance")
                    .values_list("article_id", flat=True)
                    [:cfg.refine_search_top_k]
                )
                result_ids.update(results)

        # Fetch full article data
        all_ids = list(result_ids)
        if not all_ids:
            return []

        articles = (
            Article.objects
            .select_related("feed")
            .filter(id__in=all_ids, published__gte=cutoff)
        )

        article_dicts = []
        for a in articles:
            article_dicts.append({
                "id": a.id,
                "title": a.title,
                "feed": a.feed.title if a.feed else "",
                "published": a.published.strftime("%Y-%m-%d") if a.published else "",
                "content": trim_content(a.content, cfg.context_trim_length),
            })

        logger.info("Refined '%s': %d -> %d articles",
                     story.get("label", "?"), len(story.get("article_ids", [])), len(article_dicts))

        return article_dicts
