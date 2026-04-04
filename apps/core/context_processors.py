from django.conf import settings
from django.utils.translation import get_language


def hreflang(request):
    """Build hreflang alternate URLs for the current page."""
    current_lang = get_language() or settings.LANGUAGE_CODE
    path = request.path

    # Strip current language prefix: /en/story/1/ -> /story/1/
    prefix = f"/{current_lang}"
    if path.startswith(prefix):
        path_without_lang = path[len(prefix):]
    else:
        path_without_lang = path

    base = f"{request.scheme}://{request.get_host}"
    urls = []
    for code, _name in settings.LANGUAGES:
        urls.append({"lang": code, "url": f"{base}/{code}{path_without_lang}"})
    urls.append({"lang": "x-default", "url": f"{base}/en{path_without_lang}"})

    return {"hreflang_urls": urls}
