import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.news.models import Article, ArticleChunk, DigestTopic

logger = logging.getLogger(__name__)

CHUNKS_PER_QUERY = 60


class TopicArticleCollector:
    """Collects articles per topic using embedding similarity — no duplicates across topics."""

    def __init__(self, hours=36, per_topic=25, threshold=0.25):
        self.hours = hours
        self.per_topic = per_topic
        self.threshold = threshold

    def collect(self) -> list[tuple]:
        """Return [(DigestTopic, [article_dicts])] with each article in exactly one topic."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.hours)

        # 1. Load enabled topics with their embeddings
        topics = list(
            DigestTopic.objects.filter(enabled=True).prefetch_related("embeddings")
        )
        topic_vectors = {}  # {topic.pk: [embedding_vectors]}
        for topic in topics:
            vectors = [e.embedding for e in topic.embeddings.all() if e.embedding is not None]
            if vectors:
                topic_vectors[topic.pk] = vectors

        if not topic_vectors:
            raise RuntimeError("No topic embeddings found. Run initnews or add topics in admin.")

        # 2. For each topic, find best articles via cosine similarity
        max_distance = 1.0 - self.threshold
        article_scores = defaultdict(dict)  # {article_id: {topic_pk: best_score}}

        for topic_pk, vectors in topic_vectors.items():
            for emb in vectors:
                results = (
                    ArticleChunk.objects
                    .filter(article__published__gte=cutoff)
                    .annotate(distance=CosineDistance("embedding", emb))
                    .filter(distance__lte=max_distance)
                    .order_by("distance")
                    .values_list("article_id", "distance")
                    [:CHUNKS_PER_QUERY]
                )
                for article_id, distance in results:
                    score = 1.0 - distance
                    current = article_scores[article_id].get(topic_pk, 0)
                    if score > current:
                        article_scores[article_id][topic_pk] = score

        # 3. Assign each article to its best-matching topic
        article_topics = {
            article_id: max(scores, key=scores.get)
            for article_id, scores in article_scores.items()
        }

        # 4. Fetch article data
        article_ids = list(article_topics.keys())
        articles_by_id = {
            a.id: a
            for a in Article.objects
            .select_related("feed")
            .filter(id__in=article_ids, published__gte=cutoff)
        }

        # 5. Group by topic
        topic_map = {t.pk: t for t in topics if t.pk in topic_vectors}
        grouped = {pk: [] for pk in topic_vectors}
        for article_id, topic_pk in article_topics.items():
            a = articles_by_id.get(article_id)
            if not a:
                continue
            grouped[topic_pk].append(self._article_to_dict(a))

        # 6. Sort by date descending, limit per topic, build result
        result = []
        for topic_pk in topic_vectors:
            articles = sorted(grouped[topic_pk], key=lambda x: x["published"], reverse=True)
            result.append((topic_map[topic_pk], articles[:self.per_topic]))

        total = sum(len(a) for _, a in result)
        logger.info("Collected %d articles across %d topics", total, len(result))
        for topic, articles in result:
            logger.info("  [%d] %s: %d articles", topic.order, topic.name_en, len(articles))

        return result

    @staticmethod
    def _article_to_dict(a: Article) -> dict:
        return {
            "id": a.id,
            "title": a.title,
            "feed": a.feed.title if a.feed else "",
            "published": a.published.strftime("%Y-%m-%d") if a.published else "",
            "snippet": a.summary or (a.content[:300] if a.content else ""),
        }
