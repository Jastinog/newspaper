from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import get_language, gettext_lazy as _

from apps.digest.models import Digest, DigestItem
from apps.feed.models import Article, Category
from apps.feed.services.search import SearchService
from apps.research.models import Research

SITE_NAME = _("Newspaper")
SITE_DESCRIPTION = _("Daily AI-curated news digest from 100+ RSS sources worldwide")


# ── Template Views ────────────────────────────────────────


def _latest_digest(qs, date=None):
    """Return the best-matching digest from a queryset, optionally filtered by date."""
    qs = qs.prefetch_related("items__image", "items__section__translations", "items__translations")
    if date:
        return qs.filter(date=date).first()
    return qs.order_by("-date").first()


def index(request, date=None):
    from datetime import datetime as dt
    from itertools import groupby

    current_lang = get_language() or "en"

    parsed = None
    if date:
        try:
            parsed = dt.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return redirect("index")

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

    # Pinned sections from cookie
    pinned_slugs = set(
        s for s in request.COOKIES.get("pinned_sections", "").split(",") if s
    )

    if digest:
        items = list(digest.items.select_related("section", "image").prefetch_related(
            "translations", "translations__language",
            "section__translations", "section__translations__language",
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

    # All sections for nav bar (pinned + unpinned, sorted by order)
    all_groups = sorted(pinned_groups + section_groups, key=lambda g: g["section"].order)

    return render(request, "news/index.html", {
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
    })


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
