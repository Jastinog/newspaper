from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.translation import get_language
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.services.utils import get_article_image_url
from apps.feed.models import Article, ArticleChunk
from apps.research.services.search import SimilaritySearch


# ── Similar Articles API ──────────────────────────────────


def _serialize_article(article, score=0):
    lang = get_language() or "en"
    return {
        "id": article.id,
        "title": article.title,
        "url": article.get_absolute_url(),
        "feed": article.feed.title if article.feed else "",
        "section": article.section.get_name(lang) if article.section_id else "",
        "score": score,
        "date": article.published.isoformat() if article.published else "",
        "image_url": get_article_image_url(article),
    }


@api_view(["GET"])
def similar_articles_api(request, article_id):
    """Graph data for one article: the center plus its most similar recent
    articles (embedding neighbours). A flat 2-tier graph — the day-less
    replacement for the old center→digest-items→articles tree.

    Shape matches the force-graph builder: similar articles ride in `articles`
    (level 1); `items`/`sources` stay empty (no digest grouping any more)."""
    lang = get_language() or "en"
    cache_key = f"similar_articles:{article_id}:{lang}"
    cached = cache.get(cache_key)
    if cached is not None:
        return Response(cached)

    article = get_object_or_404(
        Article.objects.select_related("feed", "section"), pk=article_id,
    )

    embeddings = list(
        ArticleChunk.objects
        .filter(article_id=article_id, chunk_index=0)
        .values_list("embedding", flat=True)[:3]
    )
    if not embeddings:
        result = {"items": [], "articles": [], "sources": []}
        cache.set(cache_key, result, 60 * 60)
        return Response(result)

    search = SimilaritySearch(days=14)
    results = search.multi_query_search(embeddings, top_k_per_query=10, final_top_k=30)

    scores = {}
    for _cid, aid, _ci, score in results:
        if aid != article_id:
            scores[aid] = max(scores.get(aid, 0), score)

    articles_data = []
    if scores:
        found = (
            Article.objects.filter(id__in=scores.keys())
            .select_related("feed", "section")
        )
        articles_data = sorted(
            (_serialize_article(a, score=round(scores.get(a.id, 0) * 100)) for a in found),
            key=lambda d: d["score"], reverse=True,
        )[:12]

    result = {"items": [], "articles": articles_data, "sources": []}
    cache.set(cache_key, result, 60 * 60)
    return Response(result)
