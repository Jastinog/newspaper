from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, F, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .models import Activity, Client, Session


def _parse_days(request, default=30, maximum=365):
    try:
        return min(int(request.GET.get("days", default)), maximum)
    except (ValueError, TypeError):
        return default


def _base_sessions(request):
    """Base queryset: sessions within the requested period."""
    since = timezone.now() - timedelta(days=_parse_days(request))
    return Session.objects.filter(started_at__gte=since)


def _base_activities(request, activity_type=None):
    """Base queryset: activities within the requested period."""
    since = timezone.now() - timedelta(days=_parse_days(request))
    qs = Activity.objects.filter(timestamp__gte=since)
    if activity_type:
        qs = qs.filter(type=activity_type)
    return qs


PAGE_VIEW = Activity.ActivityType.PAGE_VIEW


# ── Dashboard page ─────────────────────────────────────────


@staff_member_required
def dashboard(request):
    return render(request, "analytics/dashboard.html")


# ── JSON API endpoints ─────────────────────────────────────


@staff_member_required
def api_today(request):
    """Today vs yesterday stats + hourly breakdown."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    today_sessions = Session.objects.filter(started_at__gte=today_start)
    yesterday_sessions = Session.objects.filter(
        started_at__gte=yesterday_start, started_at__lt=today_start
    )

    today_page_views = Activity.objects.filter(
        type=PAGE_VIEW, timestamp__gte=today_start
    )
    yesterday_page_views = Activity.objects.filter(
        type=PAGE_VIEW, timestamp__gte=yesterday_start, timestamp__lt=today_start
    )

    bot_filter = Q(client__is_bot=True)

    today_stats = today_sessions.aggregate(
        sessions=Count("id"),
        clients=Count("client", distinct=True),
        humans=Count("id", filter=Q(is_human=True)),
        bot_sessions=Count("id", filter=bot_filter),
        bot_clients=Count("client", distinct=True, filter=bot_filter),
    )
    today_views = today_page_views.count()
    today_bot_views = today_page_views.filter(session__client__is_bot=True).count()

    yesterday_stats = yesterday_sessions.aggregate(
        clients=Count("client", distinct=True),
    )
    yesterday_views = yesterday_page_views.count()

    # Hourly breakdown (page views) — split by human/bot
    hourly = list(
        today_page_views
        .annotate(hour=ExtractHour("timestamp"))
        .values("hour")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=Q(session__client__is_bot=True)),
        )
        .order_by("hour")
    )
    hourly_map = {r["hour"]: r for r in hourly}
    hourly_full = []
    for h in range(now.hour + 1):
        row = hourly_map.get(h, {})
        hourly_full.append({
            "hour": h,
            "views": row.get("views", 0),
            "bot_views": row.get("bot_views", 0),
        })

    return JsonResponse({
        "today": {
            "views": today_views,
            "bot_views": today_bot_views,
            "clients": today_stats["clients"],
            "bot_clients": today_stats["bot_clients"],
            "humans": today_stats["humans"],
            "sessions": today_stats["sessions"],
            "bot_sessions": today_stats["bot_sessions"],
        },
        "yesterday": {
            "views": yesterday_views,
            "clients": yesterday_stats["clients"],
        },
        "hourly": hourly_full,
    })


@staff_member_required
def api_views_over_time(request):
    qs = _base_activities(request, activity_type=PAGE_VIEW)
    rows = (
        qs.annotate(date=TruncDate("timestamp"))
        .values("date")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=Q(session__client__is_bot=True)),
            clients=Count("session__client", distinct=True),
        )
        .order_by("date")
    )
    data = [
        {
            "date": r["date"].isoformat(),
            "views": r["views"],
            "bot_views": r["bot_views"],
            "clients": r["clients"],
        }
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_top_pages(request):
    qs = _base_activities(request, activity_type=PAGE_VIEW)
    rows = (
        qs.values("path", "view_name")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    return JsonResponse({"data": list(rows)})


@staff_member_required
def api_top_articles(request):
    qs = _base_activities(request, activity_type=PAGE_VIEW).filter(
        article__isnull=False
    )
    rows = (
        qs.values("article__id", "article__title")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    data = [
        {"id": r["article__id"], "title": r["article__title"], "views": r["views"]}
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_top_referrers(request):
    qs = _base_sessions(request).exclude(
        Q(referrer_domain="") | Q(referrer_domain__isnull=True)
    )
    rows = (
        qs.values("referrer_domain")
        .annotate(sessions=Count("id"))
        .order_by("-sessions")[:15]
    )
    data = [
        {"referrer_domain": r["referrer_domain"], "sessions": r["sessions"]}
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_geo(request):
    since = timezone.now() - timedelta(days=_parse_days(request))
    qs = Client.objects.filter(
        last_seen__gte=since, is_bot=False
    ).exclude(country="")
    rows = (
        qs.values("country", "country_name")
        .annotate(clients=Count("id"))
        .order_by("-clients")[:20]
    )
    return JsonResponse({"data": list(rows)})


@staff_member_required
def api_devices(request):
    since = timezone.now() - timedelta(days=_parse_days(request))
    qs = Client.objects.filter(last_seen__gte=since, is_bot=False)
    devices = list(
        qs.values("device_type").annotate(count=Count("id")).order_by("-count")
    )
    browsers = list(
        qs.exclude(browser="")
        .values("browser")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    oses = list(
        qs.exclude(os="")
        .values("os")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    return JsonResponse({"devices": devices, "browsers": browsers, "oses": oses})


@staff_member_required
def api_categories(request):
    qs = _base_activities(request, activity_type=PAGE_VIEW).filter(
        category__isnull=False
    )
    rows = (
        qs.values("category__name")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    data = [{"name": r["category__name"], "views": r["views"]} for r in rows]
    return JsonResponse({"data": data})


@staff_member_required
def api_sessions(request):
    """Session-level analytics: humans vs bots, avg duration, etc."""
    qs = _base_sessions(request)

    # Single aggregate query for all counts
    counts = qs.aggregate(
        total=Count("id"),
        humans=Count("id", filter=Q(is_human=True)),
        bots=Count("id", filter=Q(client__is_bot=True)),
        bounced=Count("id", filter=Q(page_count__lte=1)),
    )
    total = counts["total"]
    bounce_rate = round(counts["bounced"] / total * 100, 1) if total else 0

    # Average stats (only completed sessions)
    avg_stats = qs.filter(ended_at__isnull=False).aggregate(
        avg_pages=Avg("page_count"),
        avg_active_time=Avg("active_time"),
        avg_duration=Avg(F("ended_at") - F("started_at")),
    )

    # timedelta on PostgreSQL, float on SQLite
    avg_duration = avg_stats["avg_duration"]
    if avg_duration is None:
        avg_duration_secs = 0
    elif hasattr(avg_duration, "total_seconds"):
        avg_duration_secs = avg_duration.total_seconds()
    else:
        avg_duration_secs = float(avg_duration)

    return JsonResponse({
        "total": total,
        "humans": counts["humans"],
        "bots": counts["bots"],
        "bounce_rate": bounce_rate,
        "avg_pages": round(avg_stats["avg_pages"] or 0, 1),
        "avg_active_time": round(avg_stats["avg_active_time"] or 0, 0),
        "avg_duration": avg_duration_secs,
    })


@staff_member_required
def api_recent_views(request):
    """Most recent page views with client info."""
    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
    except (ValueError, TypeError):
        limit = 50

    rows = (
        Activity.objects.filter(type=PAGE_VIEW)
        .select_related("session__client")
        .order_by("-timestamp")[:limit]
    )
    data = [
        {
            "path": r.path,
            "country": r.session.client.country,
            "country_name": r.session.client.country_name,
            "city": r.session.client.city,
            "device_type": r.session.client.device_type,
            "browser": r.session.client.browser,
            "is_human": r.session.is_human,
            "is_bot": r.session.client.is_bot,
            "bot_name": r.session.client.bot_name,
            "source": r.session.source,
            "timestamp": r.timestamp.strftime("%H:%M:%S"),
        }
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_live_sessions(request):
    """Currently active sessions (no ended_at)."""
    active = (
        Session.objects.filter(ended_at__isnull=True)
        .select_related("client")
        .order_by("-started_at")[:50]
    )
    data = [
        {
            "session_id": str(s.session_id),
            "client_id": str(s.client.client_id),
            "device_type": s.client.device_type,
            "browser": s.client.browser,
            "country": s.client.country,
            "country_name": s.client.country_name,
            "city": s.client.city,
            "page_count": s.page_count,
            "active_time": s.active_time,
            "has_interaction": s.has_interaction,
            "is_human": s.is_human,
            "is_bot": s.client.is_bot,
            "bot_name": s.client.bot_name,
            "source": s.source,
            "started_at": s.started_at.strftime("%H:%M:%S"),
        }
        for s in active
    ]
    return JsonResponse({"data": data})
