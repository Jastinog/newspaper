import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from django.db import close_old_connections
from django.utils import timezone

from .models import Activity, Client, Session
from .services import build_client_defaults, resolve_path
from .utils import BOT_PATTERN, get_client_ip, parse_ua, resolve_geo

logger = logging.getLogger(__name__)

_bot_tracking_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bot_track")

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
        ua_string = request.META.get("HTTP_USER_AGENT", "")[:500]
        path = request.path

        # parse_ua is expensive (250+ regexes); skip it for requests that
        # won't render templates or need the full ua_info dict for tracking.
        is_page_request = (
            request.method in TRACKED_METHODS
            and not any(path.startswith(p) for p in SKIP_PREFIXES)
            and request.headers.get("X-Requested-With") != "XMLHttpRequest"
        )

        if is_page_request:
            ua_info = parse_ua(ua_string)
            request.is_bot = ua_info.get("is_bot", False)
        else:
            request.is_bot = bool(BOT_PATTERN.search(ua_string))
            ua_info = None

        response = self.get_response(request)

        if not is_page_request or not request.is_bot:
            return response

        # Extract from request now — the request object must not escape into the background thread
        ip = get_client_ip(request)
        referrer = request.META.get("HTTP_REFERER", "")[:2000]

        # Background thread so DB writes don't block TTFB
        _bot_tracking_pool.submit(self._track, ip, ua_string, ua_info, path, referrer)

        return response

    @staticmethod
    def _track(ip, ua_string, ua_info, path, referrer):
        """Persist bot tracking data in a background thread."""
        try:
            geo = resolve_geo(ip)

            bot_client_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"bot:{ip}:{ua_info.get('bot_name', '')}"
            )

            client, _ = Client.objects.update_or_create(
                client_id=bot_client_id,
                defaults=build_client_defaults(ua_info, ua_string, geo, ip=ip),
            )

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
        except Exception:
            logger.exception("Bot tracking failed")
        finally:
            close_old_connections()
