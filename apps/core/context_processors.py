from django.conf import settings
from django.core.cache import cache
from django.utils.translation import get_language


_SKIP_HREFLANG = ("/admin/", "/api/", "/analytics/", "/static/", "/media/")


def hreflang(request):
    """Build hreflang alternate URLs for the current page (cached)."""
    path = request.path
    if any(path.startswith(p) for p in _SKIP_HREFLANG):
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
