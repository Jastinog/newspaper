import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.core.services.ai import trim_to_tokens
from apps.core.services.utils import sanitize_text
from apps.feed.models import Article, ArticleChunk
from apps.digest.models import ArticleUse, DigestConfig, DigestSection

logger = logging.getLogger(__name__)


class SectionArticleCollector:
    """Collects articles per section using embedding similarity — no duplicates across sections."""

    def __init__(self, config: DigestConfig = None):
        self.config = config or DigestConfig.get()

    def collect(self) -> list[tuple]:
        """Return [(DigestSection, [article_dicts])] with each article in exactly one section."""
        cfg = self.config
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.hours_lookback)

        # 1. Load enabled sections with their embeddings
        sections = list(
            DigestSection.objects.filter(enabled=True).prefetch_related("embeddings")
        )
        section_vectors = {}
        for section in sections:
            vectors = [e.embedding for e in section.embeddings.all() if e.embedding is not None]
            if vectors:
                section_vectors[section.pk] = vectors

        if not section_vectors:
            raise RuntimeError("No section embeddings found. Run initdigest or add sections in admin.")

        # 2. For each section, find best articles via cosine similarity
        max_distance = 1.0 - cfg.similarity_threshold
        used_ids = self._used_article_ids()
        article_scores = defaultdict(dict)

        for section_pk, vectors in section_vectors.items():
            for emb in vectors:
                results = (
                    ArticleChunk.objects
                    .filter(article__published__gte=cutoff)
                    .exclude(article_id__in=used_ids)
                    .annotate(distance=CosineDistance("embedding", emb))
                    .filter(distance__lte=max_distance)
                    .order_by("distance")
                    .values_list("article_id", "distance")
                    [:cfg.chunks_per_query]
                )
                for article_id, distance in results:
                    score = 1.0 - distance
                    current = article_scores[article_id].get(section_pk, 0)
                    if score > current:
                        article_scores[article_id][section_pk] = score

        # 3. Assign each article to its best-matching section
        article_sections = {
            article_id: max(scores, key=scores.get)
            for article_id, scores in article_scores.items()
        }

        # 4. Fetch article data
        article_ids = list(article_sections.keys())
        articles_by_id = {
            a.id: a
            for a in Article.objects
            .select_related("feed")
            .filter(id__in=article_ids, published__gte=cutoff)
        }

        # 5. Group by section
        section_map = {s.pk: s for s in sections if s.pk in section_vectors}
        grouped = {pk: [] for pk in section_vectors}
        for article_id, section_pk in article_sections.items():
            a = articles_by_id.get(article_id)
            if not a:
                continue
            grouped[section_pk].append(self._article_to_dict(a))

        # 6. Sort by date descending, limit per section, build result
        result = []
        for section_pk in section_vectors:
            articles = sorted(grouped[section_pk], key=lambda x: x["published"], reverse=True)
            result.append((section_map[section_pk], articles[:cfg.articles_per_section]))

        total = sum(len(a) for _, a in result)
        logger.info("Collected %d articles across %d sections", total, len(result))
        for section, articles in result:
            logger.info("  [%d] %s: %d articles", section.order, section.slug, len(articles))

        return result

    def collect_section(self, section: DigestSection) -> list[dict]:
        """Collect articles for a single section (no cross-section dedup)."""
        cfg = self.config
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.hours_lookback)

        vectors = [e.embedding for e in section.embeddings.all() if e.embedding is not None]
        if not vectors:
            return []

        max_distance = 1.0 - cfg.similarity_threshold
        used_ids = self._used_article_ids()
        article_scores = {}

        for emb in vectors:
            results = (
                ArticleChunk.objects
                .filter(article__published__gte=cutoff)
                .exclude(article_id__in=used_ids)
                .annotate(distance=CosineDistance("embedding", emb))
                .filter(distance__lte=max_distance)
                .order_by("distance")
                .values_list("article_id", "distance")
                [:cfg.chunks_per_query]
            )
            for article_id, distance in results:
                score = 1.0 - distance
                if score > article_scores.get(article_id, 0):
                    article_scores[article_id] = score

        if not article_scores:
            return []

        articles = (
            Article.objects
            .select_related("feed")
            .filter(id__in=list(article_scores.keys()), published__gte=cutoff)
        )

        result = [self._article_to_dict(a) for a in articles]
        result.sort(key=lambda x: x["published"], reverse=True)

        logger.info("[%d] %s: %d articles collected", section.order, section.slug, len(result))
        return result[:cfg.articles_per_section]

    @staticmethod
    def _used_article_ids() -> set:
        """Pre-fetch IDs of articles already used in digests (one query, avoids per-embedding JOINs)."""
        return set(ArticleUse.objects.values_list("article_id", flat=True))

    def _article_to_dict(self, a: Article) -> dict:
        snippet_tokens = self.config.article_snippet_tokens
        return {
            "id": a.id,
            "title": a.title,
            "feed": a.feed.title if a.feed else "",
            "published": a.published.strftime("%Y-%m-%d") if a.published else "",
            "snippet": trim_to_tokens(sanitize_text(a.content), snippet_tokens) if a.content else "",
        }
