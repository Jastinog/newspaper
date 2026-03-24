from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext_lazy as _
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.feeds.models import Article, ArticleChunk, ArticleImage
from apps.research.services.search import SimilaritySearch

from .models import Digest, DigestItem

SITE_NAME = _("Newspaper")
SITE_DESCRIPTION = _("Daily AI-curated news digest from 100+ RSS sources worldwide")


# ── Template Views ────────────────────────────────────────


def _latest_digest(qs, date=None):
    """Return the best-matching digest from a queryset, optionally filtered by date."""
    prefetches = ("sections__items__image", "sections__items__articles__feed")
    qs = qs.prefetch_related(*prefetches)
    if date:
        return qs.filter(date=date).first()
    return qs.order_by("-date").first()


def index(request, date=None):
    from datetime import datetime as dt

    current_lang = get_language() or "en"

    parsed = None
    if date:
        try:
            parsed = dt.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return redirect("index")

    digest = _latest_digest(Digest.objects.filter(language__code=current_lang), date=parsed)

    # Fallback to English if no digest for current language
    if not digest and current_lang != "en":
        digest = _latest_digest(Digest.objects.filter(language__code="en"), date=parsed)

    # Prev/next navigation
    prev_date = next_date = None
    if digest:
        prev_digest = Digest.objects.filter(language=digest.language, date__lt=digest.date).order_by("-date").only("date").first()
        next_digest = Digest.objects.filter(language=digest.language, date__gt=digest.date).order_by("date").only("date").first()
        if prev_digest:
            prev_date = prev_digest.date
        if next_digest:
            next_date = next_digest.date

    # Section filter
    active_section = None
    filtered_items = None
    section_id = request.GET.get("section")
    if digest and section_id:
        for s in digest.sections.all():
            if str(s.id) == section_id:
                active_section = s
                filtered_items = s.items.all()
                break

    seo = {
        "title": f"{SITE_NAME} — {_('Daily News Digest')}",
        "description": SITE_DESCRIPTION,
        "canonical": request.build_absolute_uri("/"),
        "og_type": "website",
    }

    return render(request, "news/index.html", {
        "digest": digest,
        "prev_date": prev_date,
        "next_date": next_date,
        "active_section": active_section,
        "filtered_items": filtered_items,
        "seo": seo,
    })


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
        DigestItem.objects.select_related("section__digest"),
        pk=item_id,
    )

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
        return Response({"items": [], "articles": []})

    similar = (
        DigestItem.objects
        .filter(
            articles__id__in=found_ids,
            section__digest__language=item.section.digest.language,
        )
        .exclude(id=item.id)
        .select_related("section__digest", "image")
        .prefetch_related(
            Prefetch(
                "articles",
                queryset=Article.objects.select_related("feed").prefetch_related(_primary_image_prefetch()),
            ),
        )
        .distinct()
        .order_by("-section__digest__date", "-importance")[:8]
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
            "topic": si.topic,
            "summary": si.summary[:200],
            "image_url": si.best_image_url,
            "section": si.section.title,
            "date": si.section.digest.date.isoformat(),
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
