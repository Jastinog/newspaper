import logging
from datetime import datetime, timedelta, timezone

from pgvector.django import CosineDistance

from apps.feeds.models import ArticleChunk

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
        best = {}
        for emb in query_embeddings:
            results = self.search(emb, top_k=top_k_per_query)
            for chunk_id, article_id, chunk_index, score in results:
                key = (article_id, chunk_index)
                if key not in best or score > best[key][1]:
                    best[key] = (chunk_id, score)
        sorted_results = sorted(best.items(), key=lambda x: x[1][1], reverse=True)[:final_top_k]
        return [
            (chunk_id, article_id, chunk_index, score)
            for (article_id, chunk_index), (chunk_id, score) in sorted_results
        ]
