from django.conf import settings

from apps.analytics.middleware import _get_client_ip, _resolve_geo

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
        # If user already has a language cookie, skip
        if LANGUAGE_COOKIE_NAME not in request.COOKIES:
            ip = _get_client_ip(request)
            geo = _resolve_geo(ip)
            country = geo.get("country", "")
            lang = COUNTRY_LANGUAGE_MAP.get(country, settings.LANGUAGE_CODE)
            request.COOKIES[LANGUAGE_COOKIE_NAME] = lang

        return self.get_response(request)
