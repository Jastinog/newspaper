import uuid
from datetime import timedelta
from urllib.parse import urlparse

from django.urls import Resolver404, resolve
from django.utils import timezone

from .models import Client, Session
from .utils import hash_with_salt, parse_ua, resolve_geo

INACTIVITY_TIMEOUT = 300  # 5 minutes
MAX_STORED_PAGES = 200


def resolve_path(path: str):
    """Resolve Django URL name and extract article/category FK (used by BotTrackingMiddleware)."""
    view_name = ""
    article = None
    category = None
    try:
        match = resolve(path)
        view_name = match.url_name or ""
        if view_name in ("article_detail", "article_detail_redirect"):
            from apps.feed.models import Article
            article = (
                Article.objects.filter(pk=match.kwargs.get("pk"))
                .select_related("feed__category")
                .first()
            )
            if article and article.feed_id:
                category = article.feed.category
        elif view_name == "category_detail":
            from apps.feed.models import Category
            category = Category.objects.filter(slug=match.kwargs.get("slug")).first()
    except Resolver404:
        pass
    return view_name, article, category


def build_client_defaults(ua_info: dict, ua_string: str, ip_hash: str, geo: dict) -> dict:
    """Build the defaults dict for Client.objects.update_or_create."""
    return {
        "device_type": ua_info.get("device_type", "")[:20],
        "browser": ua_info.get("browser", ""),
        "os": ua_info.get("os", ""),
        "user_agent": ua_string,
        "ip_hash": ip_hash,
        "is_bot": ua_info.get("is_bot", False),
        "bot_name": ua_info.get("bot_name", "")[:100],
        "country": geo.get("country", ""),
        "country_name": geo.get("country_name", ""),
        "city": geo.get("city", ""),
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
    }


class SessionService:
    """Manages the lifecycle of a client analytics session.

    Usage (from WS consumer):
        service = SessionService(scope)
        client, session = service.open(client_id, referrer, path)
        session = service.ping(scrolls=5, pages=["/article/1"], active_time=30)
        service.close()
    """

    def __init__(self, scope):
        self._scope = scope
        self._client = None
        self._session = None

        # Parse connection info once
        self._raw_ip = self._extract_ip()
        self._ua_string = self._extract_ua()
        self._ua_info = parse_ua(self._ua_string)
        self._geo = resolve_geo(self._raw_ip)

    @property
    def client(self):
        return self._client

    @property
    def session(self):
        return self._session

    @property
    def is_active(self):
        return self._session is not None

    # ── Lifecycle ───────────────────────────────────

    def open(self, raw_client_id: str, referrer: str = "", path: str = "") -> tuple[Client, Session]:
        """Resume an active session or create a new one."""
        try:
            client_id = uuid.UUID(raw_client_id)
        except (ValueError, AttributeError, TypeError):
            client_id = uuid.uuid4()

        ip_hash = hash_with_salt(self._raw_ip) if self._raw_ip else ""

        self._client, _ = Client.objects.update_or_create(
            client_id=client_id,
            defaults=build_client_defaults(
                self._ua_info, self._ua_string, ip_hash, self._geo
            ),
        )

        now = timezone.now()
        cutoff = now - timedelta(seconds=INACTIVITY_TIMEOUT)

        # Try to resume a recent session for this client
        recent = (
            Session.objects.filter(
                client=self._client,
                source=Session.Source.WEBSOCKET,
                ended_at__isnull=True,
                last_ping_at__gte=cutoff,
            )
            .order_by("-last_ping_at")
            .first()
        )

        if recent:
            self._session = recent
            # Append the new page to the existing session
            if path:
                pages = self._session.pages or []
                pages.append({"path": path[:2000], "ts": now.strftime("%H:%M:%S")})
                Session.objects.filter(pk=self._session.pk).update(
                    last_ping_at=now,
                    page_count=len(pages),
                    pages=pages,
                )
                self._session.pages = pages
                self._session.last_ping_at = now
            return self._client, self._session

        # No active session — create a new one
        referrer_domain = ""
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc[:253]
            except Exception:
                pass

        pages = []
        if path:
            pages.append({"path": path[:2000], "ts": now.strftime("%H:%M:%S")})

        self._session = Session.objects.create(
            client=self._client,
            referrer=referrer[:2000],
            referrer_domain=referrer_domain,
            last_ping_at=now,
            page_count=len(pages),
            pages=pages,
        )

        return self._client, self._session

    def close(self):
        """End the current session."""
        if self._session:
            Session.objects.filter(pk=self._session.pk).update(
                ended_at=timezone.now(),
            )
            self._session = None

    # ── Ping ────────────────────────────────────────

    def ping(self, scrolls: int, pages: list[str], active_time: int) -> Session | None:
        """Process a 30-second ping with buffered activity.

        If the session has been inactive for > 5 minutes, closes the old one
        and opens a new session. Returns the current session.
        """
        if not self._session:
            return None

        now = timezone.now()

        # Check 5-min inactivity -> new session
        if self._session.last_ping_at:
            gap = (now - self._session.last_ping_at).total_seconds()
            if gap > INACTIVITY_TIMEOUT:
                self.close()
                self.open(
                    raw_client_id=str(self._client.client_id),
                    referrer="",
                )

        # Collect new data
        new_scrolls = max(0, int(scrolls))
        new_pages = [
            {"path": p[:2000], "ts": now.strftime("%H:%M:%S")}
            for p in pages
            if isinstance(p, str) and p
        ]

        # Fast path: no activity — just touch last_ping_at
        if not new_scrolls and not new_pages:
            Session.objects.filter(pk=self._session.pk).update(last_ping_at=now)
            self._session.last_ping_at = now
            return self._session

        # Append pages (capped to avoid unbounded growth)
        session_pages = (self._session.pages or []) + new_pages
        if len(session_pages) > MAX_STORED_PAGES:
            session_pages = session_pages[-MAX_STORED_PAGES:]

        # Update scroll stats
        new_total = (self._session.total_scrolls or 0) + new_scrolls
        active_time = min(int(active_time), 86400)
        duration_min = max(1, active_time / 60)
        spm = round(new_total / duration_min, 1)

        Session.objects.filter(pk=self._session.pk).update(
            last_ping_at=now,
            active_time=active_time,
            total_scrolls=new_total,
            spm=spm,
            page_count=len(session_pages),
            pages=session_pages,
        )

        # Update in-memory state
        self._session.last_ping_at = now
        self._session.total_scrolls = new_total
        self._session.pages = session_pages

        return self._session

    # ── Private helpers ─────────────────────────────

    def _extract_ip(self) -> str:
        headers = dict(self._scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = self._scope.get("client")
        if client:
            return client[0]
        return ""

    def _extract_ua(self) -> str:
        for header_name, header_value in self._scope.get("headers", []):
            if header_name == b"user-agent":
                return header_value.decode()[:500]
        return ""
