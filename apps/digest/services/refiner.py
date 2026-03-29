import logging
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.core.services.ai import EmbeddingClient
from apps.feed.models import Article, ArticleChunk
from apps.digest.models import ArticleUse, DigestConfig

logger = logging.getLogger(__name__)


def trim_content(text: str, max_length: int) -> str:
    """Trim text to max_length, breaking at paragraph or sentence boundaries."""
    if not text or len(text) <= max_length:
        return text or ""
    truncated = text[:max_length]
    # Prefer paragraph boundary
    last_para = truncated.rfind('\n\n')
    if last_para > max_length * 0.5:
        return truncated[:last_para].rstrip()
    # Try sentence boundary
    for sep in ('. ', '! ', '? ', '.\n', '!\n', '?\n'):
        pos = truncated.rfind(sep)
        if pos > max_length * 0.5:
            return truncated[:pos + 1]
    return truncated + "..."


class StoryRefiner:
    """Refines article collection for a specific story using LLM-generated search queries."""

    def __init__(self, embedder: EmbeddingClient = None, config: DigestConfig = None):
        self.embedder = embedder or EmbeddingClient()
        self.config = config or DigestConfig.get()

    def refine(self, story: dict, used_ids: set = None) -> tuple[list[dict], dict]:
        """Find best articles for a story using refined embedding search.

        Args:
            story: {"label": str, "article_ids": [int], "search_queries": [str]}
            used_ids: pre-loaded set of already-used article IDs (avoids per-call DB query)

        Returns:
            (article_dicts, usage) — articles with trimmed content + embedding token usage.
        """
        cfg = self.config
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.hours_lookback)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if used_ids is None:
            used_ids = set(ArticleUse.objects.values_list("article_id", flat=True))

        # Track similarity scores: article_id -> best score
        article_scores = {}

        # Original articles from analyzer get perfect relevance score
        for aid in story.get("article_ids", []):
            article_scores[aid] = 1.0

        # Embed search queries and find additional articles with scores
        queries = story.get("search_queries", [])
        if queries:
            try:
                vectors, total_tokens = self.embedder.embed_batch(queries)
                usage = {"prompt_tokens": total_tokens, "completion_tokens": 0, "total_tokens": total_tokens}
            except Exception as e:
                logger.warning("Failed to embed refine queries for '%s': %s", story.get("label"), e)
                vectors = []

            max_distance = 1.0 - cfg.similarity_threshold
            for emb in vectors:
                results = (
                    ArticleChunk.objects
                    .filter(article__published__gte=cutoff)
                    .exclude(article_id__in=used_ids)
                    .annotate(distance=CosineDistance("embedding", emb))
                    .filter(distance__lte=max_distance)
                    .order_by("distance")
                    .values_list("article_id", "distance")
                    [:cfg.refine_search_top_k]
                )
                for article_id, distance in results:
                    score = 1.0 - distance
                    if score > article_scores.get(article_id, 0):
                        article_scores[article_id] = score

        if not article_scores:
            return [], usage

        # Sort by relevance and limit to top N
        sorted_ids = sorted(article_scores, key=lambda aid: article_scores[aid], reverse=True)
        top_ids = sorted_ids[:cfg.max_articles_per_story]

        # Fetch full article data
        articles = (
            Article.objects
            .select_related("feed")
            .filter(id__in=top_ids, published__gte=cutoff)
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

        logger.info("Refined '%s': %d candidates -> %d articles",
                     story.get("label", "?"), len(article_scores), len(article_dicts))

        return article_dicts, usage
