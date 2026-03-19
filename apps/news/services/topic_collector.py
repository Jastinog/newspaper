import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.news.models import Article, ArticleChunk, TopicEmbedding

logger = logging.getLogger(__name__)

CHUNKS_PER_QUERY = 60


class TopicArticleCollector:
    """Collects articles per topic using embedding similarity — no duplicates across topics."""

    def __init__(self, hours=72, per_topic=25, threshold=0.25):
        self.hours = hours
        self.per_topic = per_topic
        self.threshold = threshold

    def collect(self) -> dict[int, list[dict]]:
        """Return {topic_index: [article_dicts]} with each article in exactly one topic."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.hours)

        # 1. Load topic embeddings grouped by index
        topic_embeddings = defaultdict(list)
        for te in TopicEmbedding.objects.all():
            topic_embeddings[te.topic_index].append(list(te.embedding))

        if not topic_embeddings:
            raise RuntimeError("No topic embeddings found. Run seed_topics first.")

        # 2. For each topic, find best articles via cosine similarity
        max_distance = 1.0 - self.threshold
        # {article_id: {topic_idx: best_score}}
        article_scores = defaultdict(dict)

        for topic_idx, embeddings in topic_embeddings.items():
            for emb in embeddings:
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
                    current = article_scores[article_id].get(topic_idx, 0)
                    if score > current:
                        article_scores[article_id][topic_idx] = score

        # 3. Assign each article to its best-matching topic
        article_topics = {}
        for article_id, scores in article_scores.items():
            best_topic = max(scores, key=scores.get)
            article_topics[article_id] = best_topic

        # 4. Fetch article data
        articles_by_id = {
            a.id: a
            for a in Article.objects
            .select_related("feed")
            .filter(id__in=list(article_topics.keys()), published__gte=cutoff)
        }

        # 5. Group by topic
        result = {i: [] for i in topic_embeddings}
        for article_id, topic_idx in article_topics.items():
            a = articles_by_id.get(article_id)
            if not a:
                continue
            result[topic_idx].append({
                "id": a.id,
                "title": a.title,
                "feed": a.feed.title if a.feed else "",
                "published": a.published.strftime("%Y-%m-%d") if a.published else "",
                "snippet": a.summary or (a.content[:300] if a.content else ""),
            })

        # Sort by date descending, limit per topic
        for topic_idx in result:
            result[topic_idx].sort(key=lambda x: x["published"], reverse=True)
            result[topic_idx] = result[topic_idx][:self.per_topic]

        total = sum(len(v) for v in result.values())
        logger.info("Collected %d articles across %d topics", total, len(result))
        for idx in sorted(result):
            logger.info("  Topic %d: %d articles", idx, len(result[idx]))

        return result
