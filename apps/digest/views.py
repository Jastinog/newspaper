from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import get_language
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.core.services.utils import get_article_image_url
from apps.feed.models import Article, ArticleChunk, ArticleImage
from apps.research.services.search import SimilaritySearch

from .models import DigestItem


# ── Sources API ──────────────────────────────────────────


@api_view(["GET"])
def item_sources_api(request, item_id):
    """Return source articles for a digest item."""
    item = get_object_or_404(DigestItem, pk=item_id)
    articles = (
        item.articles
        .select_related("feed")
        .prefetch_related(_primary_image_prefetch())
    )
    data = []
    for article in articles:
        img = article._primary_imgs[0].image.url if article._primary_imgs else ""
        if not img:
            img = get_article_image_url(article)
        data.append({
            "title": article.title,
            "url": article.url,
            "feed_title": article.feed.title if article.feed else "",
            "feed_website": article.feed.website or article.feed.url if article.feed else "",
            "image_url": img,
        })
    return Response({"sources": data})


# ── Similar Items API ─────────────────────────────────────


def _primary_image_prefetch():
    """Prefetch for fetching a single primary image per article."""
    return Prefetch(
        "images",
        queryset=ArticleImage.objects.filter(is_primary=True, downloaded=True).exclude(image=""),
        to_attr="_primary_imgs",
    )


def _serialize_article(article, score=0):
    """Serialize an article with prefetched primary image for the similar-items API."""
    return {
        "id": article.id,
        "title": article.title,
        "url": article.get_absolute_url(),
        "feed": article.feed.title if article.feed else "",
        "score": score,
        "date": article.published.isoformat() if article.published else "",
        "image_url": article._primary_imgs[0].image.url if article._primary_imgs else "",
    }


@api_view(["GET"])
def similar_items_api(request, item_id):
    """Tree: center -> similar digest items -> their articles."""
    item = get_object_or_404(
        DigestItem.objects.select_related("digest", "section"),
        pk=item_id,
    )

    lang = get_language() or "en"

    article_ids = list(item.articles.values_list("id", flat=True))
    if not article_ids:
        return Response({"items": [], "articles": [], "sources": []})

    embeddings = list(
        ArticleChunk.objects
        .filter(article_id__in=article_ids, chunk_index=0)
        .values_list("embedding", flat=True)[:3]
    )
    own_articles = list(
        item.articles
        .select_related("feed")
        .prefetch_related(_primary_image_prefetch())
        .order_by("-published")
    )
    sources_data = [_serialize_article(a) for a in own_articles]

    if not embeddings:
        return Response({"items": [], "articles": [], "sources": sources_data})

    search = SimilaritySearch(days=14)
    results = search.multi_query_search(embeddings, top_k_per_query=10, final_top_k=30)

    own_ids = set(article_ids)
    art_scores = {}
    for _cid, aid, _ci, score in results:
        if aid not in own_ids:
            art_scores[aid] = max(art_scores.get(aid, 0), score)

    found_ids = set(art_scores.keys())
    if not found_ids:
        return Response({"items": [], "articles": [], "sources": sources_data})

    similar = (
        DigestItem.objects
        .filter(
            articles__id__in=found_ids,
            digest=item.digest,
        )
        .exclude(id=item.id)
        .select_related("digest", "section", "image")
        .prefetch_related(
            "translations",
            Prefetch(
                "articles",
                queryset=Article.objects.select_related("feed").prefetch_related(_primary_image_prefetch()),
            ),
        )
        .distinct()
        .order_by("-digest__date", "-importance")[:8]
    )

    items_data = []
    covered = set()
    for si in similar:
        all_articles = list(si.articles.all())
        si_aids = {a.id for a in all_articles}
        best = max((art_scores.get(aid, 0) for aid in si_aids), default=0)
        covered |= si_aids

        items_data.append({
            "id": si.id,
            "topic": si.get_topic(lang),
            "summary": si.get_summary(lang)[:200],
            "image_url": si.best_image_url,
            "section": si.section.get_name(lang),
            "date": si.digest.date.isoformat(),
            "research_url": reverse("research", args=[si.id]),
            "score": round(best * 100),
            "articles": [
                _serialize_article(a, score=round(art_scores.get(a.id, 0) * 100))
                for a in all_articles[:4]
            ],
        })

    orphan_ids = found_ids - covered
    articles_data = []
    if orphan_ids:
        orphans = (
            Article.objects.filter(id__in=orphan_ids)
            .select_related("feed")
            .prefetch_related(_primary_image_prefetch())
            .order_by("-published")[:10]
        )
        articles_data = [
            _serialize_article(a, score=round(art_scores.get(a.id, 0) * 100))
            for a in orphans
        ]

    return Response({"items": items_data, "articles": articles_data, "sources": sources_data})
