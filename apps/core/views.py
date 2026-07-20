import re as _re
from datetime import datetime

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import BooleanField, Count, Exists, F, OuterRef, Prefetch, Q, Value, Window
from django.db.models.functions import Coalesce, RowNumber
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language, gettext_lazy as _
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import Language
from apps.core.services.utils import get_article_image_url
from apps.digest.models import Digest, DigestItem
from apps.feed.models import Article, ArticleSummary, ArticleTopic, Category, Feed, HiddenFeed, Topic
from apps.feed.services.classify import DISPLAY_THRESHOLD
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

_HOME_PER_PAGE = 30


def _topic_chips_prefetch():
    """Prefetch each article's top-scoring topics (above the display threshold)
    onto `article.top_topics`, so card templates render chips without N+1."""
    return Prefetch(
        "article_topics",
        queryset=(
            ArticleTopic.objects
            .filter(score__gte=DISPLAY_THRESHOLD)
            .select_related("topic")
            .order_by("-score")
        ),
        to_attr="top_topics",
    )


def _build_home_cursor(article):
    """Encode an article's position as `<sort_date_iso>_<pk>` for keyset paging."""
    return f"{article.sort_date.isoformat()}_{article.pk}"


def _parse_home_cursor(cursor):
    """Decode a home cursor back into (sort_date, pk); None if malformed."""
    iso, sep, pk = cursor.rpartition("_")
    if not sep:
        return None
    try:
        return datetime.fromisoformat(iso), int(pk)
    except ValueError:
        return None


def _interleave_by_feed(articles):
    """Spread a chronological page so the same source isn't shown back-to-back.

    A feed that publishes a burst lands ~20 near-identical timestamps together,
    so a straight date sort shows a long run from one source. This greedily
    picks, at each slot, the most-recent remaining article whose source differs
    from the one just shown — falling back to the next remaining when a source
    genuinely dominates. Recency is preserved as far as diversity allows (the
    newest article still leads), and it never drops or adds items, so the
    chronological cursor built before this call stays exact.

    articles_list() diversifies differently — a feed_rank Window round-robin in
    the queryset itself. home() can't reuse that: its order_by would no longer
    match the keyset cursor, and a global feed_rank abandons chronology (a stale
    feed's newest would outrank an active feed's second), which breaks the
    latest-first contract. Hence this per-page pass instead.
    """
    remaining = list(articles)  # already newest-first
    result = []
    prev_feed = None
    while remaining:
        idx = next((i for i, a in enumerate(remaining) if a.feed_id != prev_feed), 0)
        article = remaining.pop(idx)
        result.append(article)
        prev_feed = article.feed_id
    return result


def home(request):
    """Homepage: infinite-scroll feed of the genuinely latest news, newest first.

    Paging is keyset (cursor) based, not offset (?page=N). New articles arrive
    constantly at the top; an offset would shift every row down between requests
    and re-serve rows the reader already saw. A cursor pins each batch to items
    strictly older than the last one shown, so newer arrivals never cause dupes.
    """
    is_htmx = request.headers.get("HX-Request") == "true" and not request.headers.get("HX-Boosted")
    cursor = request.GET.get("cursor", "")
    lang = get_language() or "en"

    # No server-side cache here: the feed must always reflect the genuinely
    # latest articles the moment they land, so we render fresh every request.

    # Straight chronological order — the actual latest news first. Articles dated
    # in the future (feeds with bad timestamps) are not "latest", so keep them out.
    # id is the tie-breaker so the (sort_date, id) sort key is strictly total.
    now = timezone.now()
    # A card is "gist ready" only when a summary exists in the *current* language.
    lang_obj = Language.get_by_code_safe(lang)
    summary_exists = ArticleSummary.objects.filter(article=OuterRef("pk"), language=lang_obj)
    qs = (
        Article.objects.select_related("feed")  # cards only render feed.title / feed.pk
        .prefetch_related(_topic_chips_prefetch())
        .exclude(image="")
        .filter(feed__hidden__isnull=True)  # drop sources a curator marked hidden site-wide
        .annotate(
            sort_date=Coalesce("published", "created_at"),
            has_summary=Exists(summary_exists) if lang_obj else Value(False, output_field=BooleanField()),
        )
        .filter(sort_date__lte=now)
        .order_by("-sort_date", "-id")
    )

    parsed = _parse_home_cursor(cursor)
    if parsed:
        cur_date, cur_id = parsed
        qs = qs.filter(
            Q(sort_date__lt=cur_date) | Q(sort_date=cur_date, id__lt=cur_id)
        )

    # Fetch one extra row to know whether a further batch exists.
    articles = list(qs[: _HOME_PER_PAGE + 1])
    has_next = len(articles) > _HOME_PER_PAGE
    articles = articles[:_HOME_PER_PAGE]
    next_cursor = _build_home_cursor(articles[-1]) if has_next and articles else ""

    # Cursor is fixed above (chronological), so reordering the page for display
    # is safe — it changes only what the reader sees, never what the next batch is.
    articles = _interleave_by_feed(articles)

    context = {
        "articles": articles,
        "next_cursor": next_cursor,
        "is_first": not parsed,
    }
    if is_htmx:
        template = "news/_home_feed.html"
    else:
        template = "news/home.html"
        context["seo"] = {
            "title": str(SITE_NAME),
            "description": str(SITE_DESCRIPTION),
            "canonical": request.build_absolute_uri("/"),
            "og_type": "website",
        }

    return render(request, template, context)


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
        items = list(digest.items.select_related("section").prefetch_related(
            "translations", "translations__language",
            "section__translations", "section__translations__language",
            "articles",
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
            (i for i in items if i.best_image_url),
            key=lambda i: i.freshness,
            default=None,
        )
        if top_item:
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


def digest(request, date=None):
    is_htmx = request.headers.get("HX-Request") == "true" and not request.headers.get("HX-Boosted")

    context = _build_digest_context(request, date=date)
    if context is None:
        return redirect("index")

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


@staff_member_required
@require_POST
def hide_feed(request, pk):
    """Hide a whole source from the home feed for every visitor (curator-only).

    Global curation is a destructive action, so it's gated to staff via the same
    decorator the admin dashboards use; the owner is already signed into /admin
    and that session applies here too. Unhide via the admin. Real CSRF (no
    @csrf_exempt) since this is an authenticated, stateful write. Note: this only
    affects the home feed — the source stays reachable via its own page, search, etc.
    """
    feed = get_object_or_404(Feed, pk=pk)
    HiddenFeed.objects.get_or_create(feed=feed)
    return JsonResponse({"ok": True, "feed_id": feed.pk})


def article_detail(request, pk, slug=""):
    lang = get_language() or "en"

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

    if article.image:
        seo["og_image"] = request.build_absolute_uri(article.image.url)

    summary = ArticleSummary.get_for(article, Language.get_by_code_safe(lang))
    return render(request, "news/article.html", {"article": article, "seo": seo, "summary": summary})


@csrf_exempt  # unauthenticated, stateless, idempotent endpoint — CSRF adds
@require_POST  # no protection here; abuse is capped by the per-IP rate limit below.
def article_summarize(request, pk):
    """Generate (or return the stored) Russian summary for an article — HTMX POST.

    Used by the full panel on the article page. The homepage cards use the
    WebSocket flow (summary.generate) with a modal instead.
    """
    from apps.feed.services.summarize import SummaryError, generate_summary, summary_rate_ok
    from apps.feed.services.summary_guard import trusted_peer

    article = get_object_or_404(Article, pk=pk)
    lang = get_language() or "en"
    lang_obj = Language.get_by_code_safe(lang)

    def _render(**ctx):
        return render(request, "news/_article_summary.html", {"article": article, **ctx})

    # Serve an already-generated summary (in this language) without touching the API.
    existing = ArticleSummary.get_for(article, lang_obj)
    if existing:
        return _render(summary=existing)

    # A new summary means a paid API call — rate-limit it per real client. Behind
    # nginx REMOTE_ADDR is always the proxy, so use the last X-Forwarded-For hop
    # (nginx-appended, unspoofable). CSRF already pins this POST to our own page.
    peer = trusted_peer(
        request.META.get("HTTP_X_FORWARDED_FOR"), request.META.get("REMOTE_ADDR")
    )
    if not summary_rate_ok(peer):
        return _render(summary_error=_("Too many requests. Please try again later."))

    try:
        summary = generate_summary(article, language=lang_obj)
    except SummaryError as e:
        return _render(summary_error=str(e))

    return _render(summary=summary)


def article_detail_redirect(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if not article.slug:
        return article_detail(request, pk)
    return redirect(article.get_absolute_url(), permanent=True)


def category_detail(request, slug):
    page_num = request.GET.get("page", "1")

    category = get_object_or_404(Category, slug=slug)
    articles_qs = (
        Article.objects
        .filter(feed__category=category)
        .exclude(image="")
        .select_related("feed")
        .prefetch_related(_topic_chips_prefetch())
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

    return render(request, "news/category.html", {"category": category, "page": page, "seo": seo})


def topic_detail(request, slug):
    """All articles the classifier tagged with this topic (score above the
    display threshold), newest first. Mirrors category_detail but the axis is
    the article's own content, not its source."""
    page_num = request.GET.get("page", "1")
    topic = get_object_or_404(Topic, slug=slug)
    articles_qs = (
        Article.objects
        .filter(article_topics__topic=topic, article_topics__score__gte=DISPLAY_THRESHOLD)
        .exclude(image="")
        .filter(feed__hidden__isnull=True)
        .select_related("feed")
        .prefetch_related(_topic_chips_prefetch())
        .order_by("-published")
        # No .distinct() needed: topic + score are filtered in one join and
        # ArticleTopic is unique per (article, topic), so a row can't duplicate.
    )
    paginator = Paginator(articles_qs, _ARTICLES_PER_PAGE)
    page = paginator.get_page(page_num)

    seo = {
        "title": f"{topic.name} — {SITE_NAME}",
        "description": f"Latest {topic.name} news from {SITE_NAME}",
        "canonical": request.build_absolute_uri(topic.get_absolute_url()),
        "og_type": "website",
        "breadcrumbs": _breadcrumbs(
            request,
            (topic.name, topic.get_absolute_url()),
        ),
    }

    return render(request, "news/topic.html", {"topic": topic, "page": page, "seo": seo})


def story_detail(request, item_id):
    current_lang = get_language() or "en"

    item = get_object_or_404(
        DigestItem.objects.select_related("digest", "section")
        .prefetch_related(
            "translations", "translations__language",
            "section__translations", "section__translations__language",
            "articles__feed",
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
            .select_related("section")
            .prefetch_related(
                "translations", "translations__language",
                "articles__feed",
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

    return render(request, "news/story.html", {
        "item": item,
        "topic": topic,
        "summary": summary,
        "section_name": section_name,
        "source_articles": source_articles,
        "section_items": section_items,
        "has_research": bool(item._researches),
        "seo": seo,
    })


def research(request, item_id):
    lang = get_language() or "en"

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

    return render(request, "news/research.html", {
        "dive": dive,
        "item": item,
        "sources": sources,
        "hero_image": hero_image,
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
        list(Category.objects.order_by("order")),
        list(Country.objects.filter(feeds__enabled=True).distinct().order_by("name")),
    )


def feeds_list(request):
    """All feeds with filters: category, country, lean, factuality."""
    category_slug = request.GET.get("category", "")
    country_code = request.GET.get("country", "")
    lean = request.GET.get("lean", "")
    factuality = request.GET.get("factuality", "")
    q = request.GET.get("q", "").strip()

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

    # Fetch the most recently downloaded article image per feed
    feed_ids = [f.pk for f in feeds]
    latest_images = (
        Article.objects
        .filter(feed_id__in=feed_ids)
        .exclude(image="")
        .order_by("feed_id", "-published")
        .distinct("feed_id")
        .values_list("feed_id", "image")
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
    page_num = request.GET.get("page", "1")

    feed = get_object_or_404(
        Feed.objects.select_related("category", "country", "language"), pk=pk,
    )
    articles_qs = feed.articles.exclude(image="").order_by("-published")
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

    return render(request, "news/feed_detail.html", {"feed": feed, "page": page, "seo": seo})


def articles_list(request):
    """All articles with filters: category, feed, country, date range, search."""
    category_slug = request.GET.get("category", "")
    feed_id = request.GET.get("feed", "")
    country_code = request.GET.get("country", "")
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    q = request.GET.get("q", "").strip()
    page_num = request.GET.get("page", "1")

    qs = Article.objects.select_related("feed", "feed__category", "feed__country").exclude(image="")

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
