import uuid
from urllib.parse import urlparse

from django.db.models import F
from django.urls import Resolver404, resolve
from django.utils import timezone

MAX_META_KEYS = 10
MAX_META_VALUE_LEN = 500

from .models import Activity, Client, Session
from .utils import hash_with_salt, parse_ua, resolve_geo


class SessionService:
    """Manages the lifecycle of a client analytics session.

    Usage (from WS consumer):
        service = SessionService(scope)
        client, session = service.open(client_id, referrer)
        service.page_view("/some/path/", referrer="...")
        service.activity("scroll", "/some/path/", meta={"depth": 75})
        service.heartbeat(active_time=120, has_interaction=True)
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

    # ── Properties ──────────────────────────────────

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

    def open(self, raw_client_id: str, referrer: str = "") -> tuple[Client, Session]:
        """Create or update client, start a new session."""
        try:
            client_id = uuid.UUID(raw_client_id)
        except (ValueError, AttributeError, TypeError):
            client_id = uuid.uuid4()

        ip_hash = hash_with_salt(self._raw_ip) if self._raw_ip else ""

        self._client, _ = Client.objects.update_or_create(
            client_id=client_id,
            defaults={
                "device_type": self._ua_info.get("device_type", "")[:20],
                "browser": self._ua_info.get("browser", ""),
                "os": self._ua_info.get("os", ""),
                "user_agent": self._ua_string,
                "ip_hash": ip_hash,
                "is_bot": self._ua_info.get("is_bot", False),
                "country": self._geo.get("country", ""),
                "country_name": self._geo.get("country_name", ""),
                "city": self._geo.get("city", ""),
            },
        )

        referrer_domain = ""
        if referrer:
            try:
                referrer_domain = urlparse(referrer).netloc[:253]
            except Exception:
                pass

        self._session = Session.objects.create(
            client=self._client,
            referrer=referrer[:2000],
            referrer_domain=referrer_domain,
        )

        return self._client, self._session

    def close(self):
        """End the current session."""
        if self._session:
            Session.objects.filter(pk=self._session.pk).update(
                ended_at=timezone.now(),
            )
            self._session = None

    # ── Tracking ────────────────────────────────────

    def page_view(self, path: str, referrer: str = ""):
        """Record a page view activity."""
        if not self._session:
            return

        view_name, article, category = self._resolve_path(path)

        Activity.objects.create(
            session=self._session,
            type=Activity.ActivityType.PAGE_VIEW,
            path=path[:2000],
            view_name=view_name[:100],
            article=article,
            category=category,
            meta={"referrer": referrer} if referrer else {},
        )
        Session.objects.filter(pk=self._session.pk).update(
            page_count=F("page_count") + 1,
        )

    _INTERACTION_TYPES = {
        Activity.ActivityType.SCROLL,
        Activity.ActivityType.CLICK,
    }

    def activity(self, activity_type: str, path: str, meta=None):
        """Record a user interaction (scroll, click)."""
        if not self._session:
            return
        if activity_type not in self._INTERACTION_TYPES:
            return

        Activity.objects.create(
            session=self._session,
            type=activity_type,
            path=path[:2000],
            meta=self._sanitize_meta(meta),
        )

        self._mark_human()

    def heartbeat(self, active_time: int, has_interaction: bool):
        """Update session with latest active time."""
        if not self._session:
            return

        active_time = min(active_time, 86400)
        updates = {"active_time": active_time}

        if has_interaction:
            self._mark_human()

        Session.objects.filter(pk=self._session.pk).update(**updates)

    # ── Private helpers ─────────────────────────────

    def _mark_human(self):
        """Mark session as confirmed human (idempotent)."""
        if self._session and not self._session.has_interaction:
            Session.objects.filter(pk=self._session.pk).update(
                has_interaction=True,
                is_human=True,
            )
            self._session.has_interaction = True
            self._session.is_human = True

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

    @staticmethod
    def _sanitize_meta(meta):
        """Limit meta dict size to prevent storage abuse."""
        if not meta or not isinstance(meta, dict):
            return {}
        sanitized = {}
        for key in list(meta)[:MAX_META_KEYS]:
            val = meta[key]
            if isinstance(val, str):
                val = val[:MAX_META_VALUE_LEN]
            sanitized[str(key)[:100]] = val
        return sanitized

    @staticmethod
    def _resolve_path(path: str):
        """Resolve Django URL name and extract article/category FK."""
        view_name = ""
        article = None
        category = None
        try:
            match = resolve(path)
            view_name = match.url_name or ""
            if view_name in ("article_detail", "article_detail_redirect"):
                from apps.news.models import Article
                article = (
                    Article.objects.filter(pk=match.kwargs.get("pk"))
                    .select_related("feed__category")
                    .first()
                )
                if article and article.feed_id:
                    category = article.feed.category
            elif view_name == "category_detail":
                from apps.news.models import Category
                category = Category.objects.filter(slug=match.kwargs.get("slug")).first()
        except Resolver404:
            pass
        return view_name, article, category
