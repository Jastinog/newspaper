from django.conf import settings
from django.core.cache import cache
from django.utils.translation import get_language


# URL prefixes that are not user-facing pages — skipped by the page-scoped
# context processors below (hreflang, topic nav).
_SKIP_PREFIXES = ("/admin/", "/api/", "/analytics/", "/static/", "/media/")


def hreflang(request):
    """Build hreflang alternate URLs for the current page (cached)."""
    path = request.path
    if any(path.startswith(p) for p in _SKIP_PREFIXES):
        return {}

    current_lang = get_language() or settings.LANGUAGE_CODE

    cache_key = f"hreflang:{current_lang}:{path}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Strip current language prefix: /en/story/1/ -> /story/1/
    prefix = f"/{current_lang}/"
    if path.startswith(prefix):
        path_without_lang = path[len(prefix) - 1:]
    elif path == f"/{current_lang}":
        path_without_lang = "/"
    else:
        path_without_lang = path

    base = f"{request.scheme}://{request.get_host()}"
    urls = []
    for code, _name in settings.LANGUAGES:
        urls.append({"lang": code, "url": f"{base}/{code}{path_without_lang}"})
    urls.append({"lang": "x-default", "url": f"{base}/en{path_without_lang}"})

    result = {"hreflang_urls": urls}
    cache.set(cache_key, result, 60 * 60 * 24)
    return result


def bot_context(request):
    """Provide the matching base template for bot vs human rendering."""
    is_bot = getattr(request, "is_bot", False)
    return {"base_template": "news/base_bot.html" if is_bot else "news/base.html"}


def nav_topics(request):
    """Topic list for the site-wide topic nav bar (cached; skips non-page URLs)."""
    if any(request.path.startswith(p) for p in _SKIP_PREFIXES):
        return {}

    cached = cache.get("nav_topics")
    if cached is None:
        from apps.feed.models import Topic
        cached = list(Topic.objects.all())
        cache.set("nav_topics", cached, 60 * 60)
    return {"nav_topics": cached}
