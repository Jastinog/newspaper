import json
import logging
import time
from datetime import datetime

from django.db.models import Prefetch

from apps.news.models import Article, ArticleChunk, ArticleImage
from apps.news.services.ai import (
    EmbeddingClient,
    OpenAIClient,
    fix_truncated_json,
)
from apps.research.services.search import SimilaritySearch
from apps.news.services.utils import deduplicate_queries

logger = logging.getLogger(__name__)

SNIPPET_LENGTH = 300


class SearchQueryGenerator:
    """Generate diverse search queries from a user's free-text search input."""

    def __init__(self, client: OpenAIClient = None):
        self.client = client or OpenAIClient()

    def generate(self, user_query: str) -> tuple[list[str], dict]:
        system = (
            "You generate search queries for a semantic search over a news article database. "
            "The user entered a search query. Generate 4-6 diverse English search queries that "
            "approach the topic from different angles:\n"
            "- Key facts and events\n"
            "- Causes, reasons, and background\n"
            "- Consequences and implications\n"
            "- Key actors, organizations, and stakeholders\n"
            "- Related and adjacent topics\n\n"
            "Always generate queries in English regardless of the input language, "
            "since the article database is primarily in English.\n\n"
            "Output ONLY a JSON array of strings. No markdown fences."
        )
        user = f"User search: {user_query}"

        content, usage = self.client.chat(
            system=system,
            user=user,
            max_tokens=500,
            temperature=0.4,
        )

        fixed = fix_truncated_json(content)
        try:
            queries = json.loads(fixed)
            if isinstance(queries, list):
                return [q for q in queries if isinstance(q, str)][:6], usage
        except json.JSONDecodeError:
            logger.warning("Failed to parse search queries: %s", content[:200])

        return [user_query], usage


class SearchService:
    """Orchestrates search: user query → multi-angle queries → embed → vector search → articles."""

    def __init__(self):
        self.query_gen = SearchQueryGenerator()
        self.embedder = EmbeddingClient()
        self.search = SimilaritySearch(days=30)

    SORT_DATE = "date"
    SORT_RELEVANCE = "relevance"

    def search_articles(self, user_query: str, top_k: int = 30, sort: str = "date") -> dict:
        start = time.time()

        queries, _ = self.query_gen.generate(user_query)
        queries.insert(0, user_query)
        queries = deduplicate_queries(queries, limit=7)
        logger.info("Search queries for '%s': %s", user_query, queries)

        query_embeddings, _ = self.embedder.embed_batch(queries)

        search_results = self.search.multi_query_search(
            query_embeddings,
            top_k_per_query=15,
            final_top_k=top_k,
        )

        if not search_results:
            return {
                "articles": [],
                "queries": queries,
                "elapsed_ms": int((time.time() - start) * 1000),
            }

        chunk_ids = [r[0] for r in search_results]
        chunks = ArticleChunk.objects.filter(id__in=chunk_ids).only("id", "chunk_text")
        chunk_map = {c.id: c for c in chunks}

        article_scores = {}
        article_snippets = {}
        for chunk_id, article_id, _, score in search_results:
            chunk = chunk_map.get(chunk_id)
            if not chunk:
                continue
            if article_id not in article_scores or score > article_scores[article_id]:
                article_scores[article_id] = score
                text = chunk.chunk_text
                if len(text) > SNIPPET_LENGTH:
                    article_snippets[article_id] = text[:SNIPPET_LENGTH] + "\u2026"
                else:
                    article_snippets[article_id] = text

        articles = Article.objects.filter(
            id__in=list(article_scores.keys()),
        ).select_related("feed", "feed__category").prefetch_related(
            Prefetch(
                "images",
                queryset=ArticleImage.objects.filter(is_primary=True),
                to_attr="primary_images",
            ),
        )
        article_map = {a.id: a for a in articles}

        results = []
        for aid, score in article_scores.items():
            article = article_map.get(aid)
            if not article:
                continue
            results.append({
                "article": article,
                "score": round(score * 100, 1),
                "snippet": article_snippets.get(aid, ""),
            })

        if sort == self.SORT_DATE:
            results.sort(key=lambda r: r["article"].published or datetime.min, reverse=True)
        else:
            results.sort(key=lambda r: r["score"], reverse=True)

        return {
            "articles": results,
            "queries": queries,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
