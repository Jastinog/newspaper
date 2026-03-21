import hashlib
import logging
import re
from datetime import date

from django.conf import settings

logger = logging.getLogger(__name__)

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


def hash_with_salt(value: str) -> str:
    """Hash a value with daily-rotating salt for privacy."""
    salt = f"{settings.SECRET_KEY}:{date.today().isoformat()}"
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def get_client_ip(request) -> str:
    """Extract client IP from a Django HTTP request."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def resolve_geo(ip: str) -> dict:
    """Resolve IP to country/city via GeoIP database."""
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


def country_flag(code: str) -> str:
    """Convert 2-letter ISO country code to flag emoji."""
    if not code or len(code) != 2:
        return ""
    c = code.upper()
    return chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65)


def parse_ua(ua_string: str) -> dict:
    """Parse User-Agent string into device/browser/os info."""
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
