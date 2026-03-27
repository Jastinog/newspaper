from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.services.utils import get_article_image_url
from apps.digest.models import Digest, DigestItem
from apps.feed.models import Article, ArticleImage, Category, Feed
from apps.feed.services.search import SearchService
from apps.location.models import Country
from apps.research.models import Research

SITE_NAME = _("Newspaper")
SITE_DESCRIPTION = _("Daily AI-curated news digest from 100+ RSS sources worldwide")

_PINNED_COOKIE = "pinned_sections"
_PINNED_MAX_AGE = 365 * 24 * 60 * 60


def _parse_pinned_cookie(request):
    return set(s for s in request.COOKIES.get(_PINNED_COOKIE, "").split(",") if s)


# ── Template Views ────────────────────────────────────────


def _latest_digest(qs, date=None):
    """Return the best-matching digest from a queryset, optionally filtered by date."""
    qs = qs.prefetch_related("items__image", "items__section__translations", "items__translations")
    if date:
        return qs.filter(date=date).first()
    return qs.order_by("-date").first()


def _build_digest_context(request, date=None, pinned_slugs=None):
    """Build the shared context dict used by index() and toggle_pin()."""
    from datetime import datetime as dt
    from itertools import groupby

    current_lang = get_language() or "en"

    parsed = None
    if date:
        try:
            parsed = dt.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return None

    digest = _latest_digest(Digest.objects.all(), date=parsed)

    # Prev/next navigation
    prev_date = next_date = None
    if digest:
        prev_digest = Digest.objects.filter(date__lt=digest.date).order_by("-date").only("date").first()
        next_digest = Digest.objects.filter(date__gt=digest.date).order_by("date").only("date").first()
        if prev_digest:
            prev_date = prev_digest.date
        if next_digest:
            next_date = next_digest.date

    # Group items by section
    section_groups = []
    pinned_groups = []
    active_section = None
    filtered_items = None
    section_id = request.GET.get("section")

    if pinned_slugs is None:
        pinned_slugs = _parse_pinned_cookie(request)

    if digest:
        items = list(digest.items.select_related("section", "image").prefetch_related(
            "translations", "translations__language",
            "section__translations", "section__translations__language",
            "articles__feed", "articles__images",
        ).all())

        # Annotate items with localized text for template (prefetch-safe, no extra queries)
        for item in items:
            item.loc_topic = item.get_topic(current_lang)
            item.loc_summary = item.get_summary(current_lang)
            item.loc_section_name = item.section.get_name(current_lang) if item.section else ""

        if section_id:
            filtered_items = [i for i in items if str(i.section_id) == section_id]
            if filtered_items:
                active_section = filtered_items[0].section

        # Always build section_groups (needed for nav bar even when filtering)
        for _sec_id, group_items in groupby(items, key=lambda i: i.section_id):
            group_list = list(group_items)
            if group_list:
                group = {
                    "section": group_list[0].section,
                    "name": group_list[0].loc_section_name,
                    "items": group_list,
                }
                if group_list[0].section and group_list[0].section.slug in pinned_slugs:
                    pinned_groups.append(group)
                else:
                    section_groups.append(group)

    headline = digest.get_headline(current_lang) if digest else ""

    seo = {
        "title": f"{SITE_NAME} — {_('Daily News Digest')}",
        "description": SITE_DESCRIPTION,
        "canonical": request.build_absolute_uri("/"),
        "og_type": "website",
    }

    all_groups = sorted(pinned_groups + section_groups, key=lambda g: g["section"].order)

    return {
        "digest": digest,
        "headline": headline,
        "section_groups": section_groups,
        "pinned_groups": pinned_groups,
        "all_groups": all_groups,
        "pinned_slugs": pinned_slugs,
        "prev_date": prev_date,
        "next_date": next_date,
        "active_section": active_section,
        "filtered_items": filtered_items,
        "seo": seo,
    }


_HTMX_TEMPLATES = {
    "contentArea": "news/_htmx_content_area.html",
    "mainGrid": "news/_main_grid.html",
    "pinnedArea": "news/_pinned_area.html",
    "sectionNav": "news/_section_nav.html",
}


def index(request, date=None):
    context = _build_digest_context(request, date=date)
    if context is None:
        return redirect("index")

    if request.headers.get("HX-Request") == "true":
        target = request.headers.get("HX-Target", "contentArea")
        template = _HTMX_TEMPLATES.get(target, "news/_content_area.html")
        return render(request, template, context)

    return render(request, "news/index.html", context)


@require_POST
def toggle_pin(request, slug):
    """Toggle a section's pinned state (HTMX POST). Updates cookie, returns OOB swaps."""
    pinned = _parse_pinned_cookie(request)
    pinned.symmetric_difference_update({slug})

    context = _build_digest_context(request, pinned_slugs=pinned)
    if context is None:
        return redirect("index")

    response = render(request, "news/_pin_response.html", context)
    response.set_cookie(
        _PINNED_COOKIE, ",".join(sorted(pinned)),
        max_age=_PINNED_MAX_AGE, samesite="Lax", path="/",
    )
    return response


def article_detail(request, pk, slug=""):
    article = get_object_or_404(
        Article.objects.select_related("feed", "feed__category"), pk=pk,
    )
    if article.slug and article.slug != slug:
        return redirect(article.get_absolute_url(), permanent=True)

    description = article.content[:160] if article.content else article.title
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


def story_detail(request, item_id):
    current_lang = get_language() or "en"
    item = get_object_or_404(
        DigestItem.objects.select_related("digest", "section", "image")
        .prefetch_related(
            "translations", "translations__language",
            "section__translations", "section__translations__language",
            "articles__feed", "articles__images",
            Prefetch("researches", queryset=Research.objects.only("id"), to_attr="_researches"),
        ),
        pk=item_id,
    )

    topic = item.get_topic(current_lang)
    summary = item.get_summary(current_lang)
    section_name = item.section.get_name(current_lang) if item.section else ""

    source_articles = [
        {
            "title": article.title,
            "url": article.url,
            "feed_title": article.feed.title,
            "feed_lean": article.feed.lean,
            "feed_lean_display": article.feed.get_lean_display() if article.feed.lean else "",
            "image_url": get_article_image_url(article),
            "published": article.published,
            "absolute_url": article.get_absolute_url(),
        }
        for article in item.articles.all()
    ]

    seo = {
        "title": f"{topic} — {SITE_NAME}",
        "description": summary[:160] if summary else topic,
        "canonical": request.build_absolute_uri(reverse("story_detail", args=[item.pk])),
        "og_type": "article",
        "og_image": item.best_image_url,
        "published_time": item.digest.date.isoformat() if item.digest else "",
        "section": section_name,
    }

    return render(request, "news/story.html", {
        "item": item,
        "topic": topic,
        "summary": summary,
        "section_name": section_name,
        "source_articles": source_articles,
        "has_research": bool(item._researches),
        "seo": seo,
    })


def research(request, item_id):
    item = get_object_or_404(
        DigestItem.objects.select_related("digest", "section"), pk=item_id,
    )

    dive = Research.objects.filter(item=item).first()
    if not dive:
        return render(request, "news/research_loading.html", {"item": item})

    sources = dive.sources.select_related("article__feed").order_by("order")

    seo = {
        "title": f"{dive.title} — {SITE_NAME}",
        "description": dive.subtitle or dive.title,
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "article",
    }

    return render(request, "news/research.html", {
        "dive": dive,
        "item": item,
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


_ARTICLES_PER_PAGE = 40


def _filter_options():
    """Return categories and countries for browse filter dropdowns."""
    return (
        Category.objects.order_by("order"),
        Country.objects.filter(feeds__enabled=True).distinct().order_by("name"),
    )


def feeds_list(request):
    """All feeds with filters: category, country, lean, factuality."""
    qs = Feed.objects.filter(enabled=True).select_related("category", "country", "language")

    category_slug = request.GET.get("category")
    country_code = request.GET.get("country")
    lean = request.GET.get("lean")
    factuality = request.GET.get("factuality")
    q = request.GET.get("q", "").strip()

    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    if country_code:
        qs = qs.filter(country__code=country_code)
    if lean:
        qs = qs.filter(lean=lean)
    if factuality:
        qs = qs.filter(factuality=factuality)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    qs = qs.annotate(article_count=Count("articles")).order_by("category__order", "title")
    feeds = list(qs)

    categories, countries = _filter_options()

    seo = {
        "title": f"{_('Sources')} — {SITE_NAME}",
        "description": _("All news sources and RSS feeds"),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
    }

    return render(request, "news/feeds.html", {
        "feeds": feeds,
        "categories": categories,
        "countries": countries,
        "lean_choices": Feed.Lean.choices,
        "factuality_choices": Feed.Factuality.choices,
        "active_filters": {
            "category": category_slug or "",
            "country": country_code or "",
            "lean": lean or "",
            "factuality": factuality or "",
            "q": q,
        },
        "seo": seo,
    })


def feed_detail(request, pk):
    """Single feed with its articles, paginated."""
    feed = get_object_or_404(
        Feed.objects.select_related("category", "country", "language"), pk=pk,
    )
    articles_qs = (
        feed.articles
        .prefetch_related(
            Prefetch("images", queryset=ArticleImage.objects.filter(is_primary=True), to_attr="primary_images"),
        )
        .order_by("-published")
    )
    paginator = Paginator(articles_qs, _ARTICLES_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    seo = {
        "title": f"{feed.title} — {SITE_NAME}",
        "description": feed.description or (_("Articles from %(title)s") % {"title": feed.title}),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
    }

    return render(request, "news/feed_detail.html", {
        "feed": feed,
        "page": page,
        "seo": seo,
    })


def articles_list(request):
    """All articles with filters: category, feed, country, date range, search."""
    qs = (
        Article.objects
        .select_related("feed", "feed__category", "feed__country")
        .prefetch_related(
            Prefetch("images", queryset=ArticleImage.objects.filter(is_primary=True), to_attr="primary_images"),
        )
    )

    category_slug = request.GET.get("category")
    feed_id = request.GET.get("feed")
    country_code = request.GET.get("country")
    date_from = request.GET.get("from")
    date_to = request.GET.get("to")
    q = request.GET.get("q", "").strip()

    if category_slug:
        qs = qs.filter(feed__category__slug=category_slug)
    if feed_id:
        qs = qs.filter(feed_id=feed_id)
    if country_code:
        qs = qs.filter(feed__country__code=country_code)
    if date_from:
        qs = qs.filter(published__date__gte=date_from)
    if date_to:
        qs = qs.filter(published__date__lte=date_to)
    if q:
        qs = qs.filter(title__icontains=q)

    qs = qs.order_by("-published")
    paginator = Paginator(qs, _ARTICLES_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    categories, countries = _filter_options()

    seo = {
        "title": f"{_('Articles')} — {SITE_NAME}",
        "description": _("Browse all news articles"),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
    }

    return render(request, "news/articles.html", {
        "page": page,
        "categories": categories,
        "countries": countries,
        "active_filters": {
            "category": category_slug or "",
            "feed": feed_id or "",
            "country": country_code or "",
            "from": date_from or "",
            "to": date_to or "",
            "q": q,
        },
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
