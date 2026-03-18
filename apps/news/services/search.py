import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from apps.news.models import ArticleChunk
from apps.news.services.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)


class SimilaritySearch:
    """Cosine similarity search over ArticleChunk embeddings using numpy."""

    def __init__(self, days=30):
        self.days = days
        self._matrix = None  # (N, 1536) normalized
        self._chunk_ids = []  # parallel list of chunk PKs
        self._chunk_meta = []  # parallel list of (article_id, chunk_index)

    def _load_chunks(self):
        """Load chunk embeddings from the last N days into a normalized numpy matrix."""
        if self._matrix is not None:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days)
        chunks = (
            ArticleChunk.objects
            .filter(created_at__gte=cutoff)
            .values_list("id", "article_id", "chunk_index", "embedding")
        )

        ids = []
        meta = []
        vectors = []

        for chunk_id, article_id, chunk_index, emb_bytes in chunks:
            emb = EmbeddingClient.bytes_to_embedding(emb_bytes)
            vectors.append(emb)
            ids.append(chunk_id)
            meta.append((article_id, chunk_index))

        if not vectors:
            self._matrix = np.empty((0, 1536), dtype=np.float32)
            self._chunk_ids = []
            self._chunk_meta = []
            return

        self._matrix = np.array(vectors, dtype=np.float32)
        # Normalize all vectors once for cosine similarity via dot product
        norms = np.linalg.norm(self._matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._matrix = self._matrix / norms
        self._chunk_ids = ids
        self._chunk_meta = meta

        logger.info("Loaded %d chunk embeddings for similarity search", len(ids))

    def search(self, query_embedding: list[float], top_k: int = 15, threshold: float = 0.25):
        """Return top-k (chunk_id, article_id, chunk_index, score) tuples by cosine similarity."""
        self._load_chunks()

        if self._matrix.shape[0] == 0:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        query = query / (np.linalg.norm(query) or 1.0)

        scores = self._matrix @ query  # dot product = cosine similarity (both normalized)

        # Filter by threshold
        mask = scores >= threshold
        if not mask.any():
            return []

        indices = np.where(mask)[0]
        filtered_scores = scores[indices]

        # Get top-k
        if len(indices) > top_k:
            top_indices = np.argpartition(filtered_scores, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(filtered_scores[top_indices])[::-1]]
        else:
            top_indices = np.argsort(filtered_scores)[::-1]

        results = []
        for idx in top_indices:
            orig_idx = indices[idx]
            results.append((
                self._chunk_ids[orig_idx],
                self._chunk_meta[orig_idx][0],  # article_id
                self._chunk_meta[orig_idx][1],  # chunk_index
                float(filtered_scores[idx]),
            ))

        return results

    def multi_query_search(
        self,
        query_embeddings: list[list[float]],
        top_k_per_query: int = 15,
        final_top_k: int = 20,
    ):
        """Search with multiple queries, deduplicate by (article_id, chunk_index), keep best score."""
        best = {}  # (article_id, chunk_index) -> (chunk_id, score)

        for emb in query_embeddings:
            results = self.search(emb, top_k=top_k_per_query)
            for chunk_id, article_id, chunk_index, score in results:
                key = (article_id, chunk_index)
                if key not in best or score > best[key][1]:
                    best[key] = (chunk_id, score)

        # Sort by score descending and take top
        sorted_results = sorted(best.items(), key=lambda x: x[1][1], reverse=True)[:final_top_k]

        # Return (chunk_id, article_id, chunk_index, score)
        return [
            (chunk_id, article_id, chunk_index, score)
            for (article_id, chunk_index), (chunk_id, score) in sorted_results
        ]
