from django.conf import settings
from django.shortcuts import redirect
from django.utils.translation import get_language

from apps.analytics.utils import get_client_ip, resolve_geo

LANGUAGE_COOKIE_NAME = settings.LANGUAGE_COOKIE_NAME

# Country code -> language mapping
COUNTRY_LANGUAGE_MAP = {
    "UA": "uk",
    "RU": "ru",
    "BY": "ru",
    "KZ": "ru",
}


class GeoLanguageMiddleware:
    """Auto-detect language from GeoIP if user hasn't chosen one manually."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if LANGUAGE_COOKIE_NAME not in request.COOKIES:
            ip = get_client_ip(request)
            geo = resolve_geo(ip)
            country = geo.get("country", "")
            lang = COUNTRY_LANGUAGE_MAP.get(country, settings.LANGUAGE_CODE)
            request.COOKIES[LANGUAGE_COOKIE_NAME] = lang

        return self.get_response(request)


# Prefixes where 404 should NOT redirect (APIs, static, admin, etc.)
_NO_REDIRECT_PREFIXES = (
    "/admin/",
    "/api/",
    "/static/",
    "/media/",
    "/ws/",
    "/analytics/",
    "/sitemap",
    "/robots.txt",
    "/favicon.",
)


class Redirect404Middleware:
    """Redirect 404 responses to the homepage for public pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            response.status_code == 404
            and not any(request.path.startswith(p) for p in _NO_REDIRECT_PREFIXES)
        ):
            lang = get_language() or settings.LANGUAGE_CODE
            return redirect(f"/{lang}/")
        return response
