import json
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import ExtractHour, TruncDate, TruncMinute
from django.utils import timezone

from .models import Activity, Client, Session
from .utils import country_flag, format_duration

# ── Color palette ─────────────────────────────────────────
GREEN = ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.5)")
GREEN_FILL = ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.1)")
RED = ("rgb(193, 18, 31)", "rgba(193, 18, 31, 0.4)")
RED_FILL = ("rgb(193, 18, 31)", "rgba(193, 18, 31, 0.08)")
BLUE = ("rgb(59, 130, 246)", "rgba(59, 130, 246, 0.5)")
BLUE_FILL = ("rgb(59, 130, 246)", "rgba(59, 130, 246, 0.1)")
INDIGO = ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.5)")
INDIGO_FILL = ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.1)")
PURPLE = ("rgb(168, 85, 247)", "rgba(168, 85, 247, 0.5)")
PURPLE_FILL = ("rgb(168, 85, 247)", "rgba(168, 85, 247, 0.1)")
YELLOW = ("rgb(234, 179, 8)", "rgba(234, 179, 8, 0.5)")
YELLOW_FILL = ("rgb(234, 179, 8)", "rgba(234, 179, 8, 0.1)")
PINK = ("rgb(236, 72, 153)", "rgba(236, 72, 153, 0.5)")
CYAN = ("rgb(6, 182, 212)", "rgba(6, 182, 212, 0.5)")
GRAY = ("rgb(156, 163, 175)", "rgba(156, 163, 175, 0.5)")


# ── Helpers ───────────────────────────────────────────────
def _build_day_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def _build_minute_labels(now, minutes=60):
    return [
        (now - timedelta(minutes=minutes - 1 - i)).replace(second=0, microsecond=0)
        for i in range(minutes)
    ]


def _series(data_map, keys, field, default=0):
    return [data_map.get(k, {}).get(field, default) for k in keys]


def _bar_ds(label, data, color, stack=None, border_width=1):
    border, bg = color
    ds = {
        "label": label, "data": data,
        "backgroundColor": bg, "borderColor": border,
        "borderWidth": border_width, "type": "bar",
    }
    if stack:
        ds["stack"] = stack
    return ds


def _line_ds(label, data, color):
    border, bg = color
    return {
        "label": label, "data": data,
        "borderColor": border, "backgroundColor": bg,
        "borderWidth": 2, "fill": True, "tension": 0.3,
    }


def _chart(labels, datasets):
    return json.dumps({"labels": labels, "datasets": datasets})


def _pie_chart(queryset, label_field, palette):
    """Build a JSON pie/bar chart from a queryset with 'count' annotations."""
    rows = list(queryset)
    return json.dumps({
        "labels": [r[label_field].title() if label_field == "device_type" else r[label_field] for r in rows],
        "datasets": [{
            "label": "Clients",
            "data": [r["count"] for r in rows],
            "backgroundColor": palette[:len(rows)],
            "borderWidth": 0,
        }],
    })


def build_analytics_context(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    dates = _build_day_labels(now, 30)
    day_keys = [str(d) for d in dates]
    day_display = [d.strftime("%d.%m") for d in dates]

    base_pv = Activity.objects.filter(type=Activity.ActivityType.PAGE_VIEW)
    bot_filter = Q(session__client__is_bot=True)

    # ── KPI cards ─────────────────────────────────────────────
    today_pv = base_pv.filter(timestamp__gte=today_start)
    yesterday_pv = base_pv.filter(timestamp__gte=yesterday_start, timestamp__lt=today_start)

    today_views = today_pv.count()
    today_bot_views = today_pv.filter(bot_filter).count()
    today_human_views = today_views - today_bot_views

    today_visitors = (
        today_pv.exclude(session__client__is_bot=True)
        .values("session__client").distinct().count()
    )

    yesterday_views = yesterday_pv.count()
    yesterday_bot_views = yesterday_pv.filter(bot_filter).count()
    yesterday_human_views = yesterday_views - yesterday_bot_views
    yesterday_visitors = (
        yesterday_pv.exclude(session__client__is_bot=True)
        .values("session__client").distinct().count()
    )

    # View change (human only)
    views_change = today_human_views - yesterday_human_views
    visitors_change = today_visitors - yesterday_visitors

    # Sessions today
    today_sessions = Session.objects.filter(
        started_at__gte=today_start, is_human=True,
    )
    today_session_count = today_sessions.count()
    avg_duration = today_sessions.aggregate(avg=Avg("active_time"))["avg"] or 0
    avg_pages = today_sessions.aggregate(avg=Avg("page_count"))["avg"] or 0

    # Active now (sessions with activity in last 5 minutes)
    five_min_ago = now - timedelta(minutes=5)
    active_now = (
        Session.objects.filter(
            started_at__gte=five_min_ago, is_human=True,
        )
        .values("client").distinct().count()
    )

    # 7-day totals for context
    week_human_views = (
        base_pv.filter(timestamp__gte=seven_days_ago)
        .exclude(session__client__is_bot=True).count()
    )
    week_visitors = (
        base_pv.filter(timestamp__gte=seven_days_ago)
        .exclude(session__client__is_bot=True)
        .values("session__client").distinct().count()
    )

    # ── Hourly chart (today) ──────────────────────────────────
    current_hour = now.hour
    hourly_qs = list(
        today_pv
        .annotate(hour=ExtractHour("timestamp"))
        .values("hour")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=bot_filter),
        )
        .order_by("hour")
    )
    hourly_map = {r["hour"]: r for r in hourly_qs}
    hourly_labels = [f"{h}:00" for h in range(current_hour + 1)]
    hourly_human = []
    hourly_bot = []
    for h in range(current_hour + 1):
        row = hourly_map.get(h, {})
        bot = row.get("bot_views", 0)
        hourly_bot.append(bot)
        hourly_human.append(row.get("views", 0) - bot)

    hourly_chart = _chart(hourly_labels, [
        _bar_ds("Humans", hourly_human, GREEN, stack="traffic"),
        _bar_ds("Bots", hourly_bot, RED, stack="traffic"),
    ])

    # ── Minute chart (last 60 min, humans only) ───────────────
    sixty_min_ago = now - timedelta(minutes=60)
    minute_labels = _build_minute_labels(now, 60)
    minute_keys = [m.strftime("%Y-%m-%d %H:%M") for m in minute_labels]
    minute_display = [k[-5:] for k in minute_keys]

    realtime_qs = (
        base_pv.filter(timestamp__gte=sixty_min_ago)
        .exclude(session__client__is_bot=True)
        .annotate(minute=TruncMinute("timestamp"))
        .values("minute")
        .annotate(views=Count("id"))
        .order_by("minute")
    )
    realtime_map = {
        r["minute"].strftime("%Y-%m-%d %H:%M"): {"views": r["views"]}
        for r in realtime_qs
    }
    realtime_chart = _chart(minute_display, [
        _bar_ds("Page Views", _series(realtime_map, minute_keys, "views"), GREEN),
    ])

    # ── Daily charts (last 30 days) ───────────────────────────
    daily_qs = (
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=bot_filter),
            visitors=Count("session__client", distinct=True),
            human_visitors=Count(
                "session__client", distinct=True,
                filter=~bot_filter,
            ),
        )
        .order_by("day")
    )
    daily_map = {str(r["day"]): r for r in daily_qs}

    daily_human_views = []
    daily_bot_views = []
    daily_visitors_data = []
    for d in dates:
        row = daily_map.get(str(d), {})
        bot = row.get("bot_views", 0)
        daily_bot_views.append(bot)
        daily_human_views.append(row.get("views", 0) - bot)
        daily_visitors_data.append(row.get("human_visitors", 0))

    views_chart = _chart(day_display, [
        _line_ds("Human Views", daily_human_views, GREEN_FILL),
        _line_ds("Bot Views", daily_bot_views, RED_FILL),
    ])

    visitors_chart = _chart(day_display, [
        _line_ds("Unique Visitors", daily_visitors_data, BLUE_FILL),
    ])

    # Daily sessions
    daily_sessions_qs = (
        Session.objects.filter(started_at__gte=thirty_days_ago, is_human=True)
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(
            count=Count("id"),
            avg_time=Avg("active_time"),
            avg_pages=Avg("page_count"),
        )
        .order_by("day")
    )
    sessions_map = {
        str(r["day"]): {
            "count": r["count"],
            "avg_time": round(r["avg_time"] or 0),
            "avg_pages": round(float(r["avg_pages"] or 0), 1),
        }
        for r in daily_sessions_qs
    }
    sessions_chart = _chart(day_display, [
        _bar_ds("Sessions", _series(sessions_map, day_keys, "count"), INDIGO, border_width=2),
    ])

    avg_duration_chart = _chart(day_display, [
        _line_ds("Avg Duration (s)", _series(sessions_map, day_keys, "avg_time"), PURPLE_FILL),
    ])

    # ── Geographic data ───────────────────────────────────────
    all_countries = list(
        Session.objects.filter(started_at__gte=thirty_days_ago, is_human=True)
        .exclude(client__country="")
        .values("client__country", "client__country_name")
        .annotate(sessions=Count("id"), visitors=Count("client", distinct=True))
        .order_by("-sessions")
    )
    top_countries = all_countries[:10]
    for row in top_countries:
        row["flag"] = country_flag(row["client__country"])

    top_cities = list(
        Session.objects.filter(started_at__gte=thirty_days_ago, is_human=True)
        .exclude(client__city="")
        .values("client__city", "client__country", "client__country_name")
        .annotate(sessions=Count("id"), visitors=Count("client", distinct=True))
        .order_by("-sessions")[:10]
    )
    for row in top_cities:
        row["flag"] = country_flag(row["client__country"])

    # ── Top pages ─────────────────────────────────────────────
    top_pages = list(
        base_pv.filter(timestamp__gte=seven_days_ago)
        .exclude(session__client__is_bot=True)
        .values("path")
        .annotate(views=Count("id"))
        .order_by("-views")[:15]
    )

    # ── Top referrers ─────────────────────────────────────────
    top_referrers = list(
        Session.objects.filter(started_at__gte=thirty_days_ago, is_human=True)
        .exclude(referrer_domain="")
        .values("referrer_domain")
        .annotate(sessions=Count("id"))
        .order_by("-sessions")[:10]
    )

    # ── Device / Browser / OS breakdown ───────────────────────
    human_clients_30d = Client.objects.filter(
        last_seen__gte=thirty_days_ago, is_bot=False,
    )

    device_palette = [
        "rgba(99,102,241,0.7)", "rgba(34,197,94,0.7)",
        "rgba(234,179,8,0.7)", "rgba(236,72,153,0.7)",
    ]
    device_chart = _pie_chart(
        human_clients_30d.exclude(device_type="")
        .values("device_type").annotate(count=Count("id")).order_by("-count"),
        "device_type", device_palette,
    )

    browser_palette = [
        "rgba(59,130,246,0.7)", "rgba(236,72,153,0.7)", "rgba(34,197,94,0.7)",
        "rgba(234,179,8,0.7)", "rgba(168,85,247,0.7)", "rgba(6,182,212,0.7)",
        "rgba(99,102,241,0.7)", "rgba(156,163,175,0.7)",
    ]
    browser_chart = _pie_chart(
        human_clients_30d.exclude(browser="")
        .values("browser").annotate(count=Count("id")).order_by("-count")[:8],
        "browser", browser_palette,
    )

    os_palette = [
        "rgba(99,102,241,0.7)", "rgba(236,72,153,0.7)", "rgba(34,197,94,0.7)",
        "rgba(234,179,8,0.7)", "rgba(59,130,246,0.7)", "rgba(168,85,247,0.7)",
    ]
    os_chart = _pie_chart(
        human_clients_30d.exclude(os="")
        .values("os").annotate(count=Count("id")).order_by("-count")[:6],
        "os", os_palette,
    )

    # ── Bot analytics ─────────────────────────────────────────
    top_bots = list(
        Client.objects.filter(is_bot=True, last_seen__gte=thirty_days_ago)
        .exclude(bot_name="")
        .values("bot_name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    bot_requests_30d = (
        base_pv.filter(timestamp__gte=thirty_days_ago, session__client__is_bot=True)
        .count()
    )
    human_requests_30d = (
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .exclude(session__client__is_bot=True)
        .count()
    )

    # ── Bounce rate (today) ─────────────────────────────────
    if today_session_count:
        bounce_count = today_sessions.filter(page_count__lte=1).count()
        bounce_rate = round(100 * bounce_count / today_session_count)
    else:
        bounce_rate = 0

    # ── New vs Returning visitors (today) ─────────────────
    today_client_ids = (
        Session.objects.filter(started_at__gte=today_start, is_human=True)
        .values_list("client_id", flat=True).distinct()
    )
    new_visitors = Client.objects.filter(
        pk__in=today_client_ids, first_seen__gte=today_start,
    ).count()
    returning_visitors = max(0, today_visitors - new_visitors) if today_visitors else 0

    # ── Entry pages (first page in session, 7 days) ──────
    entry_page_ids = (
        Activity.objects.filter(
            type=Activity.ActivityType.PAGE_VIEW,
            session__is_human=True,
            session__started_at__gte=seven_days_ago,
        )
        .order_by("session_id", "timestamp")
        .distinct("session_id")
        .values_list("id", flat=True)
    )
    entry_pages = list(
        Activity.objects.filter(id__in=entry_page_ids)
        .values("path")
        .annotate(entries=Count("id"))
        .order_by("-entries")[:10]
    )

    # ── Live sessions table ───────────────────────────────────
    fifteen_min_ago = now - timedelta(minutes=15)
    recent_sessions = list(
        Session.objects.filter(started_at__gte=fifteen_min_ago, is_human=True)
        .select_related("client")
        .order_by("-started_at")[:20]
    )
    live_sessions = [
        {
            "country": country_flag(s.client.country),
            "city": s.client.city or "—",
            "browser": s.client.browser or "?",
            "os": s.client.os or "?",
            "device": s.client.device_type or "?",
            "pages": s.page_count,
            "time": format_duration(s.active_time),
            "started": s.started_at.strftime("%H:%M:%S"),
        }
        for s in recent_sessions
    ]

    return {
        # KPI
        "today_human_views": f"{today_human_views:,}",
        "today_bot_views": f"{today_bot_views:,}",
        "today_visitors": f"{today_visitors:,}",
        "today_session_count": f"{today_session_count:,}",
        "avg_duration": format_duration(round(avg_duration)),
        "avg_pages": f"{avg_pages:.1f}",
        "active_now": active_now,
        "views_change": views_change,
        "visitors_change": visitors_change,
        "week_human_views": f"{week_human_views:,}",
        "week_visitors": f"{week_visitors:,}",
        # Charts
        "hourly_chart": hourly_chart,
        "realtime_chart": realtime_chart,
        "views_chart": views_chart,
        "visitors_chart": visitors_chart,
        "sessions_chart": sessions_chart,
        "avg_duration_chart": avg_duration_chart,
        "device_chart": device_chart,
        "browser_chart": browser_chart,
        "os_chart": os_chart,
        # Tables
        "top_countries": top_countries,
        "top_cities": top_cities,
        "top_pages": top_pages,
        "top_referrers": top_referrers,
        "top_bots": top_bots,
        "live_sessions": live_sessions,
        # Bot stats
        "bot_requests_30d": f"{bot_requests_30d:,}",
        "human_requests_30d": f"{human_requests_30d:,}",
        # New metrics
        "bounce_rate": bounce_rate,
        "new_visitors": new_visitors,
        "returning_visitors": returning_visitors,
        "entry_pages": entry_pages,
    }
