import hashlib
import logging
import re
from datetime import date
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

BOT_KEYWORDS = [
    "bot", "crawl", "spider", "slurp", "feed", "fetch", "scan", "check",
    "monitor", "archive", "curl", "wget", "python-requests", "go-http",
    "java/", "libwww", "headless", "phantom", "selenium", "puppet",
]
BOT_PATTERN = re.compile("|".join(BOT_KEYWORDS), re.I)

# ── Known bot signatures: (regex_pattern, display_name) ────────────
# Order matters: first match wins. More specific patterns go first.
_BOT_SIGNATURE_DEFS = [
    # Search engines (specific variants first, then generic)
    ("Googlebot-Image", "Googlebot Image"),
    ("Googlebot-News", "Googlebot News"),
    ("Googlebot-Video", "Googlebot Video"),
    ("Google-InspectionTool", "Google Inspection"),
    ("Storebot-Google", "Storebot Google"),
    ("Google-Extended", "Google Extended (AI)"),
    ("FeedFetcher-Google", "Google FeedFetcher"),
    ("Google-Read-Aloud", "Google Read-Aloud"),
    ("Google-Site-Verification", "Google Verification"),
    ("GoogleOther", "GoogleOther"),
    ("Googlebot", "Googlebot"),
    ("AdsBot-Google", "Google AdsBot"),
    ("Mediapartners-Google", "Google Mediapartners"),
    ("APIs-Google", "Google APIs"),
    ("bingbot", "Bingbot"),
    ("BingPreview", "Bing Preview"),
    ("adidxbot", "Bing Ads"),
    ("msnbot", "MSN Bot"),
    ("YandexBot", "YandexBot"),
    ("YandexImages", "Yandex Images"),
    ("YandexMetrika", "Yandex Metrika"),
    ("YandexDirect", "Yandex Direct"),
    ("YandexWebmaster", "Yandex Webmaster"),
    ("YandexMedia", "Yandex Media"),
    ("YandexTurbo", "Yandex Turbo"),
    ("YandexMobileBot", "Yandex Mobile"),
    ("Yandex", "Yandex"),
    ("Baiduspider", "Baidu Spider"),
    ("DuckDuckBot", "DuckDuckBot"),
    (r"Yahoo!?\s*Slurp", "Yahoo Slurp"),
    ("Sogou", "Sogou Spider"),
    ("Applebot", "Applebot"),
    ("Qwantify", "Qwant Bot"),
    ("PetalBot", "PetalBot (Huawei)"),
    ("SeznamBot", "Seznam Bot"),
    ("Naver", "Naver Bot"),
    ("Yeti/", "Naver Yeti"),
    ("coccocbot", "Coc Coc Bot"),
    ("Mojeek", "MojeekBot"),
    ("BraveSearch", "Brave Search"),
    ("ia_archiver", "Alexa/Archive"),
    (r"archive\.org_bot", "Internet Archive"),
    ("special_archiver", "Internet Archive"),
    ("Mail\\.RU_Bot", "Mail.ru Bot"),
    # AI / LLM crawlers
    ("GPTBot", "GPTBot (OpenAI)"),
    ("ChatGPT-User", "ChatGPT User"),
    ("OAI-SearchBot", "OpenAI SearchBot"),
    ("ClaudeBot", "ClaudeBot (Anthropic)"),
    ("Claude-Web", "Claude Web"),
    ("anthropic-ai", "Anthropic AI"),
    ("PerplexityBot", "PerplexityBot"),
    ("Perplexity-User", "Perplexity User"),
    ("Cohere-ai", "Cohere AI"),
    ("CCBot", "Common Crawl"),
    ("Bytespider", "Bytespider (ByteDance)"),
    ("Diffbot", "Diffbot"),
    ("Meta-ExternalAgent", "Meta AI"),
    ("meta-externalagent", "Meta AI"),
    ("AI2Bot", "AI2Bot (Allen AI)"),
    ("Ai2Bot-Dolma", "AI2Bot Dolma"),
    ("YouBot", "YouBot"),
    ("Amazonbot", "Amazonbot"),
    ("Timpibot", "Timpibot"),
    ("Friendly_Crawler", "Friendly Crawler"),
    ("Webzio", "Webz.io"),
    ("img2dataset", "img2dataset"),
    ("Scrapy", "Scrapy"),
    # Social media / messaging
    ("facebookexternalhit", "Facebook"),
    ("FacebookBot", "FacebookBot"),
    ("Facebot", "Facebook"),
    ("TelegramBot", "Telegram"),
    ("Twitterbot", "Twitter/X"),
    ("LinkedInBot", "LinkedIn"),
    ("WhatsApp", "WhatsApp"),
    ("Discordbot", "Discord"),
    ("Pinterest", "Pinterest"),
    ("Slackbot", "Slack"),
    ("Slack-ImgProxy", "Slack"),
    ("Viber", "Viber"),
    ("Snapchat", "Snapchat"),
    ("vkShare", "VKontakte"),
    ("Mastodon", "Mastodon"),
    ("redditbot", "Reddit"),
    ("SkypeUriPreview", "Skype"),
    ("Signal", "Signal"),
    ("Line/", "LINE"),
    ("Embedly", "Embedly"),
    ("Microsoft Teams", "MS Teams"),
    ("SkypeSpaces", "MS Teams"),
    (r"Rocket\.Chat", "Rocket.Chat"),
    # SEO / analytics bots
    ("AhrefsBot", "Ahrefs"),
    ("AhrefsSiteAudit", "Ahrefs Audit"),
    ("SemrushBot", "Semrush"),
    ("MJ12bot", "Majestic"),
    ("DotBot", "Moz DotBot"),
    ("Rogerbot", "Moz Rogerbot"),
    ("BLEXBot", "BLEXBot"),
    ("DataForSeoBot", "DataForSEO"),
    ("serpstatbot", "Serpstat"),
    ("Screaming Frog", "Screaming Frog"),
    ("SISTRIX", "Sistrix"),
    ("ContentKing", "ContentKing"),
    ("Botify", "Botify"),
    ("OnCrawl", "OnCrawl"),
    ("deepcrawl", "DeepCrawl"),
    ("SEOkicks", "SEOkicks"),
    ("seokicks", "SEOkicks"),
    ("Domains Project", "Domains Project"),
    ("BomboraBot", "BomboraBot"),
    ("ZoominfoBot", "ZoominfoBot"),
    ("CriteoBot", "CriteoBot"),
    ("Megaindex", "MegaIndex"),
    ("LinkpadBot", "LinkpadBot"),
    ("BacklinkCrawler", "BacklinkCrawler"),
    # Monitoring / uptime
    ("UptimeRobot", "UptimeRobot"),
    ("Pingdom", "Pingdom"),
    ("NewRelicPinger", "New Relic"),
    ("nrbot", "New Relic"),
    ("StatusCake", "StatusCake"),
    ("Datadog", "Datadog"),
    ("Site24x7", "Site24x7"),
    ("Zabbix", "Zabbix"),
    ("GTmetrix", "GTmetrix"),
    ("Chrome-Lighthouse", "Lighthouse"),
    ("PTST", "WebPageTest"),
    ("Checkly", "Checkly"),
    ("BetterUptime", "Better Uptime"),
    ("NodePing", "NodePing"),
    ("Prometheus", "Prometheus"),
    ("Nagios", "Nagios"),
    ("check_http", "Nagios"),
    ("HetrixTools", "HetrixTools"),
    # Feed readers
    ("Feedly", "Feedly"),
    ("Feedbin", "Feedbin"),
    ("NewsBlur", "NewsBlur"),
    ("Inoreader", "Inoreader"),
    ("Tiny Tiny RSS", "Tiny Tiny RSS"),
    ("FreshRSS", "FreshRSS"),
    ("Miniflux", "Miniflux"),
    ("Flipboard", "Flipboard"),
    ("AppleNewsBot", "Apple News"),
    ("Feedspot", "Feedspot"),
    ("theoldreader", "The Old Reader"),
    ("SimplePie", "SimplePie"),
    ("UniversalFeedParser", "Feed Parser"),
    ("feedparser", "Feed Parser"),
    # Dev / HTTP tools
    ("curl/", "curl"),
    ("wget/", "wget"),
    ("python-requests", "Python Requests"),
    ("python-urllib", "Python urllib"),
    ("Python-urllib", "Python urllib"),
    ("aiohttp", "Python aiohttp"),
    ("python-httpx", "Python HTTPX"),
    ("httpx", "Python HTTPX"),
    ("Go-http-client", "Go HTTP Client"),
    ("Java/", "Java"),
    ("Apache-HttpClient", "Apache HttpClient"),
    ("okhttp", "OkHttp"),
    ("node-fetch", "Node Fetch"),
    ("axios/", "Axios"),
    ("undici", "Node Undici"),
    ("libwww-perl", "Perl LWP"),
    ("Ruby", "Ruby"),
    ("PHP/", "PHP"),
    ("GuzzleHttp", "PHP Guzzle"),
    ("Dart/", "Dart"),
    ("PostmanRuntime", "Postman"),
    ("insomnia", "Insomnia"),
    ("HTTPie", "HTTPie"),
    ("HeadlessChrome", "Headless Chrome"),
    ("PhantomJS", "PhantomJS"),
    ("Selenium", "Selenium"),
    ("Puppeteer", "Puppeteer"),
    ("Playwright", "Playwright"),
    # CDN / infrastructure
    ("Amazon Route 53", "AWS Route 53"),
    ("Amazon CloudFront", "CloudFront"),
    ("Cloudflare-Healthchecks", "Cloudflare Health"),
    ("Cloudflare-AMP", "Cloudflare AMP"),
    # Security scanners
    ("Nmap", "Nmap"),
    ("Nikto", "Nikto"),
    ("sqlmap", "SQLMap"),
    ("Wapiti", "Wapiti"),
    ("ZAP", "OWASP ZAP"),
    ("Nuclei", "Nuclei"),
    ("Qualys", "Qualys"),
    ("Nessus", "Nessus"),
    ("Acunetix", "Acunetix"),
    ("Burp", "Burp Suite"),
    ("CensysInspect", "Censys"),
    ("Expanse", "Expanse"),
    ("NetSystemsResearch", "NetSystems"),
    # Meta / Facebook crawlers
    ("meta-webindexer", "Meta Web Indexer"),
    # Microsoft
    ("Microsoft Office", "MS Office"),
    ("ms-office", "MS Office"),
    # Other crawlers
    ("Turnitin", "Turnitin"),
    ("Grammarly", "Grammarly"),
    ("W3C_Validator", "W3C Validator"),
    ("W3C-checklink", "W3C Link Check"),
    (r"validator\.nu", "Validator.nu"),
    ("Netcraft", "Netcraft"),
    ("BuiltWith", "BuiltWith"),
    ("Wappalyzer", "Wappalyzer"),
    ("SimilarTech", "SimilarTech"),
    ("Datanyze", "Datanyze"),
    ("HubSpot", "HubSpot"),
    ("Zapier", "Zapier"),
    ("Twingly", "Twingly"),
    ("Mediatoolkit", "Mediatoolkit"),
    ("ICC-Crawler", "ICC Crawler"),
    ("SurdotlyBot", "SurdotlyBot"),
    ("AspiegelBot", "AspiegelBot"),
    ("Seekport", "Seekport"),
    ("ISSCyberRiskCrawler", "ISS Cyber Risk"),
    ("Riddler", "Riddler"),
    ("Researchscan", "Researchscan"),
    ("MauiBot", "MauiBot"),
    ("Nimbostratus-Bot", "Nimbostratus"),
    ("webprosbot", "WebPros"),
    ("Cookiebot", "Cookiebot"),
]

BOT_SIGNATURES = [
    (re.compile(pattern, re.I), name) for pattern, name in _BOT_SIGNATURE_DEFS
]


def identify_bot(ua_string: str) -> str:
    """Return a human-readable bot name from the User-Agent, or '' if unknown."""
    if not ua_string:
        return ""
    for pattern, name in BOT_SIGNATURES:
        if pattern.search(ua_string):
            return name
    return ""


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


_EMPTY_GEO = {"country": "", "country_name": "", "city": "", "latitude": None, "longitude": None}


def resolve_geo(ip: str) -> dict:
    """Resolve IP to country/city/coordinates via GeoIP database (cached)."""
    if not ip or not _get_geoip_reader():
        return _EMPTY_GEO
    return _resolve_geo_cached(ip)


@lru_cache(maxsize=2048)
def _resolve_geo_cached(ip: str) -> dict:
    try:
        resp = _get_geoip_reader().city(ip)
        return {
            "country": (resp.country.iso_code or "")[:2],
            "country_name": (resp.country.name or "")[:100],
            "city": (resp.city.name or "")[:200],
            "latitude": resp.location.latitude,
            "longitude": resp.location.longitude,
        }
    except Exception:
        return _EMPTY_GEO


def country_flag(code: str) -> str:
    """Convert 2-letter ISO country code to flag emoji."""
    if not code or len(code) != 2:
        return ""
    c = code.upper()
    return chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65)


def format_duration(seconds: int) -> str:
    """Seconds -> human-readable duration like '3m12s'."""
    if not seconds:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _empty_result(is_bot: bool, bot_name: str) -> dict:
    return {
        "is_bot": is_bot,
        "device_type": "bot" if is_bot else "",
        "browser": "",
        "os": "",
        "bot_name": bot_name,
    }


def parse_ua(ua_string: str) -> dict:
    """Parse User-Agent string into device/browser/os info + bot identification."""
    bot_name = identify_bot(ua_string)
    has_bot_signal = bool(BOT_PATTERN.search(ua_string)) or bool(bot_name)

    try:
        from user_agents import parse
        ua = parse(ua_string)
    except Exception:
        return _empty_result(has_bot_signal, bot_name)

    is_bot = ua.is_bot or has_bot_signal

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
        "bot_name": bot_name,
    }
