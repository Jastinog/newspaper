import hashlib
import logging
import re
from datetime import date
from urllib.parse import urlparse

from django.conf import settings
from django.urls import resolve, Resolver404

logger = logging.getLogger(__name__)

# Paths to skip
SKIP_PREFIXES = ("/static/", "/admin/", "/api/", "/analytics/", "/favicon")
SKIP_EXTENSIONS = re.compile(r"\.(css|js|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|map)$", re.I)

# Bot keywords in User-Agent
BOT_KEYWORDS = [
    "bot", "crawl", "spider", "slurp", "feed", "fetch", "scan", "check",
    "monitor", "archive", "curl", "wget", "python-requests", "go-http",
    "java/", "libwww", "headless", "phantom", "selenium", "puppet",
]
BOT_PATTERN = re.compile("|".join(BOT_KEYWORDS), re.I)

# GeoIP reader (lazy init)
_geoip_reader = None
_geoip_init_attempted = False


def _get_geoip_reader():
    global _geoip_reader, _geoip_init_attempted
    if _geoip_init_attempted:
        return _geoip_reader
    _geoip_init_attempted = True
    db_path = getattr(settings, "GEOIP_DATABASE_PATH", None)
    if db_path:
        try:
            import geoip2.database

            _geoip_reader = geoip2.database.Reader(db_path)
        except Exception as e:
            logger.warning("GeoIP database not available: %s", e)
    return _geoip_reader


def _hash_with_salt(value: str) -> str:
    salt = f"{settings.SECRET_KEY}:{date.today().isoformat()}"
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def _get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _parse_ua(ua_string: str) -> dict:
    try:
        from user_agents import parse

        ua = parse(ua_string)
        is_bot = ua.is_bot or bool(BOT_PATTERN.search(ua_string))

        if is_bot:
            device_type = "bot"
        elif ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        else:
            device_type = "desktop"

        return {
            "is_bot": is_bot,
            "device_type": device_type,
            "browser": ua.browser.family[:50],
            "os": ua.os.family[:50],
        }
    except Exception:
        is_bot = bool(BOT_PATTERN.search(ua_string))
        return {
            "is_bot": is_bot,
            "device_type": "bot" if is_bot else "",
            "browser": "",
            "os": "",
        }


def _resolve_geo(ip: str) -> dict:
    reader = _get_geoip_reader()
    if not reader or not ip:
        return {"country": "", "country_name": "", "city": ""}
    try:
        resp = reader.city(ip)
        return {
            "country": (resp.country.iso_code or "")[:2],
            "country_name": (resp.country.name or "")[:100],
            "city": (resp.city.name or "")[:200],
        }
    except Exception:
        return {"country": "", "country_name": "", "city": ""}


class AnalyticsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:
            logger.exception("Analytics middleware error")
        return response

    def _record(self, request, response):
        # Only track successful HTML responses
        if response.status_code != 200:
            return
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return

        path = request.path

        # Skip static/admin/api/analytics paths
        if any(path.startswith(p) for p in SKIP_PREFIXES):
            return
        if SKIP_EXTENSIONS.search(path):
            return

        # Resolve URL name and extract article/category
        view_name = ""
        article_id = None
        category_slug = None
        try:
            match = resolve(path)
            view_name = match.url_name or ""
            if view_name in ("article_detail", "article_detail_redirect"):
                article_id = match.kwargs.get("pk")
            elif view_name == "category_detail":
                category_slug = match.kwargs.get("slug")
        except Resolver404:
            pass

        # User-Agent parsing
        ua_string = request.META.get("HTTP_USER_AGENT", "")[:500]
        ua_info = _parse_ua(ua_string)

        # IP hashing
        raw_ip = _get_client_ip(request)
        ip_hash = _hash_with_salt(raw_ip) if raw_ip else ""
        session_hash = _hash_with_salt(f"{raw_ip}:{ua_string}") if raw_ip else ""

        # Referrer
        referrer = request.META.get("HTTP_REFERER", "")[:2000]
        referrer_domain = ""
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc[:253]
            except Exception:
                pass

        # GeoIP
        geo = _resolve_geo(raw_ip)

        # Resolve FKs
        article = None
        category = None
        if article_id:
            from apps.news.models import Article

            article = Article.objects.filter(pk=article_id).first()
            if article and article.feed_id:
                try:
                    category = article.feed.category
                except Exception:
                    pass
        elif category_slug:
            from apps.news.models import Category

            category = Category.objects.filter(slug=category_slug).first()

        from apps.analytics.models import PageView

        PageView.objects.create(
            path=path[:2000],
            view_name=view_name[:100],
            article=article,
            category=category,
            ip_hash=ip_hash,
            session_hash=session_hash,
            user_agent=ua_string,
            is_bot=ua_info["is_bot"],
            device_type=ua_info["device_type"][:20],
            browser=ua_info["browser"],
            os=ua_info["os"],
            referrer=referrer,
            referrer_domain=referrer_domain,
            country=geo["country"],
            country_name=geo["country_name"],
            city=geo["city"],
        )
