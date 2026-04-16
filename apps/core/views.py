import re as _re

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Prefetch, Q, Window
from django.db.models.functions import Coalesce, RowNumber
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import Language
from apps.core.services.utils import get_article_image_url
from apps.digest.models import Digest, DigestItem
from apps.feed.models import Article, ArticleImage, Category, Feed
from apps.feed.services.search import SearchService
from apps.location.models import Country
from apps.research.models import Research

SITE_NAME = _("Newspaper")
SITE_DESCRIPTION = _("Daily AI-curated news digest from 100+ RSS sources worldwide")


def _breadcrumbs(request, *crumbs):
    """Build breadcrumb list with absolute URLs. Each crumb is (name, url_name_or_path)."""
    base = f"{request.scheme}://{request.get_host()}"
    lang = get_language() or "en"
    result = [{"name": str(SITE_NAME), "url": f"{base}/{lang}/"}]
    for name, url in crumbs:
        if url.startswith("/"):
            result.append({"name": str(name), "url": f"{base}{url}"})
        else:
            result.append({"name": str(name), "url": f"{base}{reverse(url)}"})
    return result


def _cache_suffix(request):
    """Return ':bot' for bot requests to separate cached HTML variants."""
    return ":bot" if getattr(request, "is_bot", False) else ""


_MD_CHARS = _re.compile(r"[\*_#\[\]\(\)>`~|]")


def _og_description(text, limit=200):
    """Collapse whitespace, strip Markdown, and truncate for og:description."""
    if not text:
        return ""
    text = _MD_CHARS.sub("", text)
    return " ".join(text.split())[:limit]

_PINNED_COOKIE = "pinned_sections"
_PINNED_MAX_AGE = 365 * 24 * 60 * 60


def _parse_pinned_cookie(request):
    return set(s for s in request.COOKIES.get(_PINNED_COOKIE, "").split(",") if s)


# ── Template Views ────────────────────────────────────────


def _latest_digest(qs, date=None):
    """Return the best-matching *completed* digest, optionally filtered by date."""
    qs = qs.filter(stage=Digest.Stage.DONE)
    if date:
        return qs.filter(date=date).first()
    return qs.first()


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
        done = Digest.objects.filter(stage=Digest.Stage.DONE)
        prev_digest = done.filter(date__lt=digest.date).only("date").first()
        next_digest = done.filter(date__gt=digest.date).order_by("date").only("date").first()
        if prev_digest:
            prev_date = prev_digest.date
        if next_digest:
            next_date = next_digest.date

    # Group items by section
    items = []
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
        ).all())

        # Annotate items with localized text, skip empty items
        for item in items:
            item.loc_topic = item.get_topic(current_lang)
            item.loc_summary = item.get_summary(current_lang)
            item.loc_section_name = item.section.get_name(current_lang) if item.section else ""
        items = [i for i in items if i.loc_topic and i.loc_summary]

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

    # Pick OG image from already-loaded items to avoid an extra query
    og_image = ""
    if digest and items:
        top_item = max(
            (i for i in items if i.image_id and getattr(i.image, "image", "")),
            key=lambda i: i.freshness,
            default=None,
        )
        if top_item and top_item.best_image_url:
            og_image = f"{settings.SITE_URL}{top_item.best_image_url}"

    seo = {
        "title": f"{SITE_NAME} — {_('Daily News Digest')}",
        "description": SITE_DESCRIPTION,
        "canonical": f"{settings.SITE_URL}/",
        "og_type": "website",
        "og_image": og_image,
    }

    all_groups = sorted(pinned_groups + section_groups, key=lambda g: g["section"].order)

    return {
        "digest": digest,
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
    is_htmx = request.headers.get("HX-Request") == "true" and not request.headers.get("HX-Boosted")
    has_pinned = bool(request.COOKIES.get(_PINNED_COOKIE, ""))
    has_section = bool(request.GET.get("section"))
    lang = get_language() or "en"

    # Cache context dict, not the rendered response — caching the full HttpResponse
    # would bake one user's CSRF token into the HTML served to everyone.
    can_cache = not is_htmx and not has_pinned and not has_section
    context = None
    if can_cache:
        cache_key = f"index:{lang}:{date or 'latest'}"
        context = cache.get(cache_key)

    if context is None:
        context = _build_digest_context(request, date=date)
        if context is None:
            return redirect("index")
        if can_cache and context.get("digest"):
            digest_date = str(context["digest"].date)
            cache.set(f"index:{lang}:{digest_date}", context, 60 * 60)
            if not date:
                cache.set(f"index:{lang}:latest", context, 60 * 5)

    if is_htmx:
        target = request.headers.get("HX-Target", "contentArea")
        template = _HTMX_TEMPLATES.get(target, "news/_content_area.html")
        return render(request, template, context)

    return render(request, "news/index.html", context)


@csrf_exempt
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
    lang = get_language() or "en"
    cache_key = f"article:{pk}:{lang}{_cache_suffix(request)}"
    cached = cache.get(cache_key)

    if cached is not None:
        cached_slug, html = cached
        if cached_slug and cached_slug != slug:
            return redirect(reverse("article_detail", kwargs={"pk": pk, "slug": cached_slug}), permanent=True)
        return HttpResponse(html)

    article = get_object_or_404(
        Article.objects.select_related("feed", "feed__category"), pk=pk,
    )
    if article.slug and article.slug != slug:
        return redirect(article.get_absolute_url(), permanent=True)

    description = _og_description(article.content) or article.title
    crumbs = [(_("Articles"), "articles_list")]
    if article.feed.category:
        crumbs.append((article.feed.category.name, article.feed.category.get_absolute_url()))
    crumbs.append((article.title, article.get_absolute_url()))

    seo = {
        "title": f"{article.title} — {SITE_NAME}",
        "description": description,
        "canonical": request.build_absolute_uri(article.get_absolute_url()),
        "og_type": "article",
        "published_time": article.published.isoformat() if article.published else "",
        "section": article.feed.category.name if article.feed.category else "",
        "breadcrumbs": _breadcrumbs(request, *crumbs),
    }

    hero_image = article.images.filter(is_primary=True).exclude(image="").first()
    if hero_image and hero_image.image:
        seo["og_image"] = request.build_absolute_uri(hero_image.image.url)

    response = render(request, "news/article.html", {"article": article, "seo": seo, "hero_image": hero_image})
    cache.set(cache_key, (article.slug, response.content), 60 * 60)
    return response


def article_detail_redirect(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not article.slug:
        return article_detail(request, pk)
    return redirect(article.get_absolute_url(), permanent=True)


def category_detail(request, slug):
    page_num = request.GET.get("page", "1")
    lang = get_language() or "en"
    cache_key = f"category:{slug}:{page_num}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)

    if html is not None:
        return HttpResponse(html)

    category = get_object_or_404(Category, slug=slug)
    articles_qs = (
        Article.objects
        .filter(feed__category=category)
        .select_related("feed")
        .order_by("-published")
    )
    paginator = Paginator(articles_qs, _ARTICLES_PER_PAGE)
    page = paginator.get_page(page_num)

    seo = {
        "title": f"{category.name} — {SITE_NAME}",
        "description": f"Latest {category.name} news from {SITE_NAME}",
        "canonical": request.build_absolute_uri(category.get_absolute_url()),
        "og_type": "website",
        "breadcrumbs": _breadcrumbs(
            request,
            (_("Articles"), "articles_list"),
            (category.name, category.get_absolute_url()),
        ),
    }

    response = render(request, "news/category.html", {"category": category, "page": page, "seo": seo})
    cache.set(cache_key, response.content, 60 * 15)
    return response


def story_detail(request, item_id):
    current_lang = get_language() or "en"
    cache_key = f"story:{item_id}:{current_lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)

    if html is not None:
        return HttpResponse(html)

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

    # Other items from the same section
    section_items = []
    if item.section and item.digest:
        siblings = (
            DigestItem.objects
            .filter(digest=item.digest, section=item.section)
            .exclude(pk=item.pk)
            .select_related("section", "image")
            .prefetch_related(
                "translations", "translations__language",
                "articles__feed", "articles__images",
            )
        )
        for si in siblings:
            si.loc_topic = si.get_topic(current_lang)
            si.loc_summary = si.get_summary(current_lang)
        section_items = [si for si in siblings if si.loc_topic and si.loc_summary]

    seo = {
        "title": f"{topic} — {SITE_NAME}",
        "description": _og_description(summary) or topic,
        "canonical": request.build_absolute_uri(reverse("story_detail", args=[item.pk])),
        "og_type": "article",
        "og_image": request.build_absolute_uri(item.best_image_url) if item.best_image_url else "",
        "published_time": item.digest.date.isoformat() if item.digest else "",
        "section": section_name,
        "breadcrumbs": _breadcrumbs(
            request,
            (_("Digest"), "index"),
            (topic, reverse("story_detail", args=[item.pk])),
        ),
    }

    response = render(request, "news/story.html", {
        "item": item,
        "topic": topic,
        "summary": summary,
        "section_name": section_name,
        "source_articles": source_articles,
        "section_items": section_items,
        "has_research": bool(item._researches),
        "seo": seo,
    })
    cache.set(cache_key, response.content, 60 * 60)
    return response


def research(request, item_id):
    lang = get_language() or "en"
    cache_key = f"research:{item_id}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)

    if html is not None:
        return HttpResponse(html)

    item = get_object_or_404(
        DigestItem.objects.select_related("digest", "section")
        .prefetch_related("translations", "translations__language"),
        pk=item_id,
    )

    dive = Research.objects.filter(item=item, language=Language.get_by_code(lang)).first()
    if not dive:
        return render(request, "news/research_loading.html", {
            "item": item,
            "topic": item.get_topic(lang),
        })

    sources = list(
        dive.sources.select_related("article__feed")
        .prefetch_related("article__images")
        .order_by("order")
    )

    for s in sources:
        s.image_url = get_article_image_url(s.article)

    hero_image = next(filter(None, (s.image_url for s in sources)), "")

    seo = {
        "title": f"{dive.title} — {SITE_NAME}",
        "description": _og_description(dive.subtitle) or dive.title,
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "article",
        "og_image": request.build_absolute_uri(hero_image) if hero_image else "",
        "breadcrumbs": _breadcrumbs(
            request,
            (_("Digest"), "index"),
            (item.get_topic(lang), reverse("story_detail", args=[item.pk])),
            (dive.title, request.get_full_path()),
        ),
    }

    response = render(request, "news/research.html", {
        "dive": dive,
        "item": item,
        "sources": sources,
        "hero_image": hero_image,
        "seo": seo,
    })
    cache.set(cache_key, response.content, 60 * 60)
    return response


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

    lang = get_language() or "en"
    cache_key = f"search:{hash(query)}:{sort}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)
    if html is not None:
        return HttpResponse(html)

    service = SearchService()
    results = service.search_articles(query, top_k=30, sort=sort)

    seo = {
        "title": f"{query} — {_('Search')} — {SITE_NAME}",
        "description": f"{_('Search results for')} {query}",
    }

    response = render(request, "news/search.html", {
        "query": query,
        "sort": sort,
        "results": results.get("articles", []),
        "queries": results.get("queries", []),
        "elapsed_ms": results.get("elapsed_ms", 0),
        "seo": seo,
    })
    cache.set(cache_key, response.content, 60 * 30)
    return response


_ARTICLES_PER_PAGE = 40


def _filter_options():
    """Return categories and countries for browse filter dropdowns."""
    return cache.get_or_set(
        "filter_options",
        lambda: (
            list(Category.objects.order_by("order")),
            list(Country.objects.filter(feeds__enabled=True).distinct().order_by("name")),
        ),
        3600,
    )


def feeds_list(request):
    """All feeds with filters: category, country, lean, factuality."""
    category_slug = request.GET.get("category", "")
    country_code = request.GET.get("country", "")
    lean = request.GET.get("lean", "")
    factuality = request.GET.get("factuality", "")
    q = request.GET.get("q", "").strip()
    lang = get_language() or "en"

    cache_key = f"feeds_list:{category_slug}:{country_code}:{lean}:{factuality}:{q}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)
    if html is not None:
        return HttpResponse(html)

    qs = Feed.objects.filter(enabled=True).select_related("category", "country", "language")
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

    # Fetch the most recently downloaded image per feed
    feed_ids = [f.pk for f in feeds]
    latest_images = (
        ArticleImage.objects
        .filter(article__feed_id__in=feed_ids)
        .exclude(image="")
        .order_by("article__feed_id", "-created_at")
        .distinct("article__feed_id")
        .values_list("article__feed_id", "image")
    )
    feed_image_map = dict(latest_images)
    for feed in feeds:
        rel = feed_image_map.get(feed.pk, "")
        feed.thumb = f"{settings.MEDIA_URL}{rel}" if rel else ""

    categories, countries = _filter_options()

    seo = {
        "title": f"{_('Sources')} — {SITE_NAME}",
        "description": _("All news sources and RSS feeds"),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
        "breadcrumbs": _breadcrumbs(request, (_("Sources"), "feeds_list")),
    }

    response = render(request, "news/feeds.html", {
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
    cache.set(cache_key, response.content, 60 * 15)
    return response


def feed_detail(request, pk):
    """Single feed with its articles, paginated."""
    page_num = request.GET.get("page", "1")
    lang = get_language() or "en"
    cache_key = f"feed_detail:{pk}:{page_num}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)

    if html is not None:
        return HttpResponse(html)

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
    page = paginator.get_page(page_num)

    seo = {
        "title": f"{feed.title} — {SITE_NAME}",
        "description": feed.description or (_("Articles from %(title)s") % {"title": feed.title}),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
        "breadcrumbs": _breadcrumbs(
            request,
            (_("Sources"), "feeds_list"),
            (feed.title, request.get_full_path()),
        ),
    }

    response = render(request, "news/feed_detail.html", {"feed": feed, "page": page, "seo": seo})
    cache.set(cache_key, response.content, 60 * 15)
    return response


def articles_list(request):
    """All articles with filters: category, feed, country, date range, search."""
    category_slug = request.GET.get("category", "")
    feed_id = request.GET.get("feed", "")
    country_code = request.GET.get("country", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    q = request.GET.get("q", "").strip()
    page_num = request.GET.get("page", "1")
    lang = get_language() or "en"

    cache_key = f"articles:{category_slug}:{feed_id}:{country_code}:{date_from}:{date_to}:{q}:{page_num}:{lang}{_cache_suffix(request)}"
    html = cache.get(cache_key)
    if html is not None:
        return HttpResponse(html)

    qs = (
        Article.objects
        .select_related("feed", "feed__category", "feed__country")
        .prefetch_related(
            Prefetch("images", queryset=ArticleImage.objects.filter(is_primary=True), to_attr="primary_images"),
        )
    )

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

    qs = qs.annotate(
        sort_date=Coalesce("published", "created_at"),
        feed_rank=Window(
            expression=RowNumber(),
            partition_by=F("feed_id"),
            order_by=F("sort_date").desc(),
        ),
    ).order_by("feed_rank", "-sort_date")
    paginator = Paginator(qs, _ARTICLES_PER_PAGE)
    page = paginator.get_page(page_num)

    categories, countries = _filter_options()

    seo = {
        "title": f"{_('Articles')} — {SITE_NAME}",
        "description": _("Browse all news articles"),
        "canonical": request.build_absolute_uri(request.get_full_path()),
        "og_type": "website",
        "breadcrumbs": _breadcrumbs(request, (_("Articles"), "articles_list")),
    }

    response = render(request, "news/articles.html", {
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
    cache.set(cache_key, response.content, 60 * 15)
    return response


def set_language_get(request, lang):
    """Switch UI language via GET — no CSRF token needed."""
    from urllib.parse import urlparse

    valid = {code for code, _ in settings.LANGUAGES}
    if lang not in valid:
        lang = settings.LANGUAGE_CODE

    current = request.GET.get("next", "")
    # Block open redirects: only allow relative paths on this host
    if current:
        parsed = urlparse(current)
        if parsed.netloc or parsed.scheme:
            current = ""

    # Strip existing lang prefix and prepend new one
    for code, _ in settings.LANGUAGES:
        if current == f"/{code}" or current.startswith(f"/{code}/"):
            current = current[len(f"/{code}"):]
            break

    next_url = f"/{lang}{current}" if current else f"/{lang}/"
    response = redirect(next_url)
    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=365 * 24 * 60 * 60, samesite="Lax", path="/")
    return response


def manifest_json(request):
    manifest = {
        "name": "Newspaper — Daily News Digest",
        "short_name": "Newspaper",
        "description": "Daily AI-curated news digest from 100+ RSS sources worldwide",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f5f0e8",
        "theme_color": "#2c2c2c",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📰</text></svg>",
                "sizes": "any",
                "type": "image/svg+xml",
            }
        ],
    }
    return JsonResponse(manifest, content_type="application/manifest+json")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /analytics/",
        "",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
        f"Sitemap: {request.build_absolute_uri('/sitemap-news.xml')}",
        f"RSS: {request.build_absolute_uri('/feed/rss/')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
