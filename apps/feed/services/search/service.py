import logging
import time
from datetime import datetime, timezone

from apps.core.services.utils import markdown_to_plain
from apps.feed.models import Article, ArticleChunk
from apps.feed.services.embed import LocalEmbedder
from apps.feed.services.search.similarity import SimilaritySearch

logger = logging.getLogger(__name__)

SNIPPET_LENGTH = 300
_DATETIME_MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)


class SearchService:
    """Orchestrates search: user query \u2192 local embed \u2192 vector search \u2192 articles.

    Fully local: the query is embedded with the same on-device model that
    embedded the articles (no OpenAI, no query expansion)."""

    def __init__(self):
        self.embedder = LocalEmbedder.instance()
        self.search = SimilaritySearch(days=30)

    SORT_DATE = "date"
    SORT_RELEVANCE = "relevance"
    # Cosine floor tuned for BGE: its similarities sit higher than OpenAI's, so
    # unrelated pairs still score ~0.35 — anything below this is noise.
    RELEVANCE_FLOOR = 0.5

    def search_articles(self, user_query: str, top_k: int = 30, sort: str = "date") -> dict:
        start = time.time()

        queries = [user_query]
        query_embedding = self.embedder.embed_one(user_query, is_query=True)

        search_results = self.search.search(
            query_embedding, top_k=top_k, threshold=self.RELEVANCE_FLOOR,
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
        best_chunk_text = {}
        for chunk_id, article_id, _, score in search_results:
            chunk = chunk_map.get(chunk_id)
            if not chunk:
                continue
            if article_id not in article_scores or score > article_scores[article_id]:
                article_scores[article_id] = score
                best_chunk_text[article_id] = chunk.chunk_text

        articles = Article.objects.filter(
            id__in=list(article_scores.keys()),
        ).select_related("feed", "feed__category")
        article_map = {a.id: a for a in articles}

        results = []
        for aid, score in article_scores.items():
            article = article_map.get(aid)
            if not article:
                continue
            # Clean Markdown/URLs out once per result (only the winning chunk)
            # before truncating, so raw "[text](url)" link syntax never leaks
            # into a snippet. Slice first \u2014 only SNIPPET_LENGTH chars survive.
            text = markdown_to_plain(best_chunk_text.get(aid, "")[:SNIPPET_LENGTH * 3])
            snippet = text[:SNIPPET_LENGTH] + "\u2026" if len(text) > SNIPPET_LENGTH else text
            results.append({
                "article": article,
                "score": round(score * 100, 1),
                "snippet": snippet,
            })

        if sort == self.SORT_DATE:
            results.sort(key=lambda r: r["article"].published or _DATETIME_MIN_UTC, reverse=True)
        else:
            results.sort(key=lambda r: r["score"], reverse=True)

        return {
            "articles": results,
            "queries": queries,
            "elapsed_ms": int((time.time() - start) * 1000),
        }
