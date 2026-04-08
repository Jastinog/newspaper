import logging
from datetime import datetime, timedelta, timezone

from django.db import connection
from pgvector.django import CosineDistance

from apps.feed.models import ArticleChunk

logger = logging.getLogger(__name__)


class SimilaritySearch:
    """Cosine similarity search over ArticleChunk embeddings using pgvector."""

    def __init__(self, days=30):
        self.days = days

    def _base_qs(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days)
        return ArticleChunk.objects.filter(created_at__gte=cutoff)

    def search(self, query_embedding: list[float], top_k: int = 15, threshold: float = 0.25):
        max_distance = 1.0 - threshold
        results = (
            self._base_qs()
            .annotate(distance=CosineDistance("embedding", query_embedding))
            .filter(distance__lte=max_distance)
            .order_by("distance")
            .values_list("id", "article_id", "chunk_index", "distance")[:top_k]
        )
        return [
            (chunk_id, article_id, chunk_index, 1.0 - distance)
            for chunk_id, article_id, chunk_index, distance in results
        ]

    def multi_query_search(self, query_embeddings, top_k_per_query=15, final_top_k=20):
        if not query_embeddings:
            return []
        # Single embedding — use the simple ORM path
        if len(query_embeddings) == 1:
            return self.search(query_embeddings[0], top_k=final_top_k)

        # Multiple embeddings — combine into a single query with LEAST()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days)
        max_distance = 0.75  # 1.0 - 0.25 threshold

        distance_exprs = ", ".join(
            f"embedding <=> %s::vector" for _ in query_embeddings
        )
        sql = f"""
            SELECT id, article_id, chunk_index, distance FROM (
                SELECT id, article_id, chunk_index,
                       LEAST({distance_exprs}) AS distance
                FROM feed_articlechunk
                WHERE created_at >= %s
            ) sub
            WHERE distance <= %s
            ORDER BY distance
            LIMIT %s
        """
        params = list(query_embeddings) + [cutoff, max_distance, final_top_k]

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        best = {}
        for chunk_id, article_id, chunk_index, distance in rows:
            score = 1.0 - distance
            key = (article_id, chunk_index)
            if key not in best or score > best[key][1]:
                best[key] = (chunk_id, score)

        sorted_results = sorted(best.items(), key=lambda x: x[1][1], reverse=True)[:final_top_k]
        return [
            (chunk_id, article_id, chunk_index, score)
            for (article_id, chunk_index), (chunk_id, score) in sorted_results
        ]
