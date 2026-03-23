from django.db.models import Count, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext_lazy as _
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Article, ArticleChunk, ArticleImage, Category, DeepDive, Digest, DigestItem, Feed
from .services.deep_dive.search import SimilaritySearch
from .services.search import SearchService
from .serializers import (
    ArticleDetailSerializer,
    ArticleListSerializer,
    ArticleUpdateSerializer,
    CategorySerializer,
    FeedSerializer,
)

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

    digest = _latest_digest(Digest.objects.filter(language=current_lang), date=parsed)

    # Fallback to English if no digest for current language
    if not digest and current_lang != "en":
        digest = _latest_digest(Digest.objects.filter(language="en"), date=parsed)

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


def article_detail(request, pk, slug=""):
    article = get_object_or_404(
        Article.objects.select_related("feed", "feed__category"), pk=pk,
    )
    if article.slug and article.slug != slug:
        return redirect(article.get_absolute_url(), permanent=True)

    description = article.summary[:160] if article.summary else article.title
    seo = {
        "title": f"{article.title} — {SITE_NAME}",
        "description": description,
        "canonical": request.build_absolute_uri(article.get_absolute_url()),
        "og_type": "article",
        "published_time": article.published.isoformat() if article.published else "",
        "section": article.feed.category.name if article.feed.category else "",
    }

    return render(request, "news/article.html", {"article": article, "seo": seo})


def article_detail_redirect(request, pk):
    article = get_object_or_404(Article, pk=pk)
    return redirect(article.get_absolute_url(), permanent=True)


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    articles = (
        Article.objects
        .filter(feed__category=category)
        .select_related("feed")
        .order_by("-published")[:100]
    )

    seo = {
        "title": f"{category.name} — {SITE_NAME}",
        "description": f"Latest {category.name} news from {SITE_NAME}",
        "canonical": request.build_absolute_uri(category.get_absolute_url()),
        "og_type": "website",
    }

    return render(request, "news/category.html", {
        "category": category,
        "articles": articles,
        "seo": seo,
    })


def deep_dive(request, item_id):
    item = get_object_or_404(
        DigestItem.objects.select_related("section__digest"), pk=item_id,
    )

    dive = DeepDive.objects.filter(item=item).first()
    if not dive:
        return render(request, "news/deep_dive_loading.html", {"item": item})

    sources = dive.sources.select_related("article__feed").order_by("order")

    seo = {
        "title": f"{dive.title} — {SITE_NAME}",
        "description": dive.subtitle or dive.title,
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "article",
    }

    return render(request, "news/deep_dive.html", {
        "dive": dive,
        "section": item.section,
        "sources": sources,
        "seo": seo,
    })


def search(request):
    query = request.GET.get("q", "").strip()

    if not query:
        seo = {
            "title": f"{_('Search')} — {SITE_NAME}",
            "description": SITE_DESCRIPTION,
        }
        return render(request, "news/search.html", {"query": "", "seo": seo})

    sort = request.GET.get("sort", "date")
    if sort not in ("date", "relevance"):
        sort = "date"

    service = SearchService()
    results = service.search_articles(query, top_k=30, sort=sort)

    seo = {
        "title": f"{query} — {_('Search')} — {SITE_NAME}",
        "description": f"{_('Search results for')} {query}",
    }

    return render(request, "news/search.html", {
        "query": query,
        "sort": sort,
        "results": results.get("articles", []),
        "queries": results.get("queries", []),
        "elapsed_ms": results.get("elapsed_ms", 0),
        "seo": seo,
    })


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /analytics/",
        "",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


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
        return Response({"items": [], "articles": []})

    embeddings = list(
        ArticleChunk.objects
        .filter(article_id__in=article_ids, chunk_index=0)
        .values_list("embedding", flat=True)[:3]
    )
    if not embeddings:
        return Response({"items": [], "articles": []})

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

    # ── Similar DigestItems with nested articles ──
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
            "deep_dive_url": reverse("deep_dive", args=[si.id]),
            "score": round(best * 100),
            "articles": [_serialize_article(a) for a in all_articles[:4]],
        })

    # ── Standalone articles (not in any found digest item) ──
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

    return Response({"items": items_data, "articles": articles_data})


# ── API Views ─────────────────────────────────────────────


class ArticleListAPI(generics.ListAPIView):
    serializer_class = ArticleListSerializer

    def get_queryset(self):
        qs = Article.objects.select_related("feed", "feed__category").all()
        category = self.request.query_params.get("category")
        feed = self.request.query_params.get("feed")
        is_read = self.request.query_params.get("read")
        is_starred = self.request.query_params.get("starred")

        if category:
            qs = qs.filter(feed__category__slug=category)
        if feed:
            qs = qs.filter(feed_id=feed)
        if is_read is not None:
            qs = qs.filter(read=is_read.lower() in ("true", "1"))
        if is_starred is not None:
            qs = qs.filter(starred=is_starred.lower() in ("true", "1"))
        return qs


class ArticleDetailAPI(generics.RetrieveUpdateAPIView):
    queryset = Article.objects.select_related("feed", "feed__category").all()

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return ArticleUpdateSerializer
        return ArticleDetailSerializer


class FeedListAPI(generics.ListAPIView):
    serializer_class = FeedSerializer

    def get_queryset(self):
        return Feed.objects.select_related("category").annotate(
            article_count=Count("articles"),
        ).all()


class CategoryListAPI(generics.ListAPIView):
    serializer_class = CategorySerializer
    queryset = Category.objects.all()


@api_view(["POST"])
def toggle_feed_api(request, pk):
    feed = get_object_or_404(Feed, pk=pk)
    feed.enabled = not feed.enabled
    feed.save(update_fields=["enabled"])
    return Response({"id": feed.id, "enabled": feed.enabled})
