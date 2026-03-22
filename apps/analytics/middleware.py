import uuid
from urllib.parse import urlparse

from django.utils import timezone

from .models import Activity, Client, Session
from .services import build_client_defaults, resolve_path
from .utils import get_client_ip, hash_with_salt, parse_ua, resolve_geo

# Paths to skip tracking (prefixes)
SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/admin/",
    "/analytics/",
    "/favicon.",
    "/robots.txt",
    "/sitemap",
    "/.well-known/",
    "/ws/",
    "/api/",
)

# Only track these HTTP methods
TRACKED_METHODS = {"GET", "HEAD"}


class BotTrackingMiddleware:
    """Track HTTP requests from bots that don't use WebSocket.

    Creates Client + Session (source=http) + Activity for each bot request.
    Human browsers connect via WebSocket and are tracked there instead.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only track GET/HEAD requests
        if request.method not in TRACKED_METHODS:
            return response

        # Skip non-page paths
        path = request.path
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return response

        # Skip successful responses to AJAX/API-like requests
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return response

        # Parse UA and only track bots
        ua_string = request.META.get("HTTP_USER_AGENT", "")[:500]
        ua_info = parse_ua(ua_string)

        if not ua_info.get("is_bot", False):
            return response

        # Get IP and geo info
        ip = get_client_ip(request)
        ip_hash = hash_with_salt(ip) if ip else ""
        geo = resolve_geo(ip)

        # Create or update client (use IP hash as stable identifier for bots)
        # Bots don't have localStorage client_id, so we derive one from IP + UA
        bot_client_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"bot:{ip_hash}:{ua_info.get('bot_name', '')}"
        )

        client, _ = Client.objects.update_or_create(
            client_id=bot_client_id,
            defaults=build_client_defaults(ua_info, ua_string, ip_hash, geo),
        )

        # Create a short-lived HTTP session (immediately closed)
        referrer = request.META.get("HTTP_REFERER", "")[:2000]
        referrer_domain = ""
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc[:253]
            except Exception:
                pass

        session = Session.objects.create(
            client=client,
            source=Session.Source.HTTP,
            referrer=referrer,
            referrer_domain=referrer_domain,
            page_count=1,
            ended_at=timezone.now(),
        )

        view_name, article, category = resolve_path(path)

        Activity.objects.create(
            session=session,
            type=Activity.ActivityType.PAGE_VIEW,
            path=path[:2000],
            view_name=view_name[:100],
            article=article,
            category=category,
        )

        return response
