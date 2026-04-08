from datetime import timedelta

from django.contrib.admin import site as admin_site
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from django.db.models import OuterRef, Subquery

from .models import Activity, Client, Session
from .utils import country_flag, format_country, format_duration


@staff_member_required
def analytics_dashboard(request):
    context = {**admin_site.each_context(request), "title": "Analytics"}
    return render(request, "admin/analytics_dashboard.html", context)


def _browser_short(browser: str) -> str:
    b = (browser or "").lower()
    if "chrome" in b and "edg" not in b:
        return "Cr"
    if "safari" in b:
        return "Sa"
    if "firefox" in b:
        return "Ff"
    if "edg" in b:
        return "Ed"
    if "opera" in b or "opr" in b:
        return "Op"
    if "samsung" in b:
        return "Sm"
    return "??"


_DEVICE_SHORT = {"mobile": "Mb", "tablet": "Tb", "desktop": "Dk"}


def _device_short(device_type: str) -> str:
    return _DEVICE_SHORT.get((device_type or "").lower(), "??")


def _hour_labels(now):
    """Build 25 hour-mark labels covering [now-24h .. now]."""
    now_local = timezone.localtime(now)
    return [
        (now_local - timedelta(hours=24 - i)).strftime("%H")
        for i in range(25)
    ]


@staff_member_required
def analytics_timeline_api(request):
    """Return rolling 24-hour timeline: sessions from now-24h to now."""
    now = timezone.now()
    window_start = now - timedelta(hours=24)

    sessions = list(
        Session.objects.filter(
            started_at__gte=window_start,
            source=Session.Source.WEBSOCKET,
            client__is_bot=False,
        )
        .select_related("client")
        .defer("pages")
        .order_by("started_at")
    )

    # Group by client
    clients_map = {}
    for s in sessions:
        c = s.client
        if c.pk not in clients_map:
            flag = country_flag(c.country)
            city = (c.city or "Unknown")[:8].ljust(8)
            br = _browser_short(c.browser)
            dev = _device_short(c.device_type)
            label = f"{flag} {city} {br} {dev}" if flag else f"   {city} {br} {dev}"
            clients_map[c.pk] = {
                "id": c.pk,
                "label": label,
                "ip": c.ip or "",
                "sessions": [],
            }

        # Convert to hours from left edge (0 = 24h ago, 24 = now)
        start_ago = (now - s.started_at).total_seconds() / 3600
        start_h = 24 - min(24, start_ago)

        # Wall time end (full connection span)
        wall_end = s.ended_at or s.last_ping_at or s.started_at
        end_ago = (now - wall_end).total_seconds() / 3600
        end_h = max(24 - min(24, max(0, end_ago)), start_h + 0.05)

        # Active time end
        active_hours = max(s.active_time, 0) / 3600
        active_end_h = start_h + max(active_hours, 0.05)

        clients_map[c.pk]["sessions"].append({
            "start": round(start_h, 3),
            "end": round(end_h, 3),
            "active_end": round(min(active_end_h, end_h), 3),
            "duration": format_duration(s.active_time),
            "spm": s.spm,
            "scrolls": s.total_scrolls,
        })

    # Sort clients: group by IP so same-IP clients are adjacent
    sorted_clients = sorted(clients_map.values(), key=lambda c: c["ip"])

    return JsonResponse({
        "clients": sorted_clients,
        "hour_labels": _hour_labels(now),
    })


@staff_member_required
def analytics_bots_timeline_api(request):
    """Return rolling 24-hour timeline of bot requests grouped by bot name."""
    now = timezone.now()
    window_start = now - timedelta(hours=24)

    # Lightweight query — only fetch the two columns we need
    rows = (
        Session.objects.filter(
            started_at__gte=window_start,
            source=Session.Source.HTTP,
            client__is_bot=True,
        )
        .values_list("client__bot_name", "started_at")
    )

    bots_map = {}
    for bot_name, started_at in rows:
        name = bot_name or "Unknown"
        if name not in bots_map:
            bots_map[name] = {"name": name, "count": 0, "minutes": set()}

        bots_map[name]["count"] += 1
        start_ago = (now - started_at).total_seconds() / 3600
        # Round to the nearest minute bucket (0–1440) then back to hours
        minute_bucket = round((24 - min(24, start_ago)) * 60)
        bots_map[name]["minutes"].add(minute_bucket / 60)

    minute_h = 1 / 60  # one minute in hours
    for bot in bots_map.values():
        # Merge consecutive minutes into [start, end] ranges
        sorted_mins = sorted(bot["minutes"])
        ranges = []
        for h in sorted_mins:
            if ranges and h - ranges[-1][1] < minute_h + 0.0001:
                ranges[-1][1] = h + minute_h
            else:
                ranges.append([h, h + minute_h])
        bot["sessions"] = [[round(r[0], 4), round(r[1], 4)] for r in ranges]
        del bot["minutes"]

    bots_list = sorted(bots_map.values(), key=lambda b: b["count"], reverse=True)

    return JsonResponse({
        "bots": bots_list,
        "hour_labels": _hour_labels(now),
    })


@staff_member_required
def bot_history_api(request):
    """Return paginated session history for a specific bot name."""
    bot_name = request.GET.get("bot_name", "")
    if not bot_name:
        return JsonResponse({"error": "bot_name required"}, status=400)

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid page"}, status=400)

    per_page = 50
    offset = (page - 1) * per_page

    first_activity_path = Subquery(
        Activity.objects.filter(session=OuterRef("pk")).values("path")[:1]
    )

    qs = (
        Session.objects.filter(client__bot_name=bot_name)
        .select_related("client")
        .annotate(request_path=first_activity_path)
        .order_by("-started_at")
    )

    # Fetch one extra row to detect next page without a separate COUNT query
    rows = list(qs[offset : offset + per_page + 1])
    has_more = len(rows) > per_page
    sessions = rows[:per_page]

    history = []
    for s in sessions:
        c = s.client
        history.append({
            "started_at": timezone.localtime(s.started_at).strftime("%d.%m.%Y %H:%M"),
            "ip": c.ip or "—",
            "country": format_country(c.country, c.country_name),
            "city": c.city or "—",
            "path": s.request_path or "—",
            "user_agent": (c.user_agent or "—")[:120],
        })

    return JsonResponse({
        "bot_name": bot_name,
        "page": page,
        "has_more": has_more,
        "sessions": history,
    })


@staff_member_required
def client_history_api(request, client_pk):
    """Return full session history for a single client."""
    client = get_object_or_404(Client, pk=client_pk)

    sessions = (
        client.sessions
        .order_by("-started_at")[:200]
        .values(
            "started_at", "ended_at", "source", "active_time",
            "page_count", "total_scrolls", "spm", "pages",
            "referrer_domain",
        )
    )

    history = []
    for s in sessions:
        history.append({
            "started_at": timezone.localtime(s["started_at"]).strftime("%d.%m.%Y %H:%M"),
            "ended_at": timezone.localtime(s["ended_at"]).strftime("%H:%M") if s["ended_at"] else None,
            "source": s["source"],
            "active_time": format_duration(s["active_time"]),
            "page_count": s["page_count"],
            "total_scrolls": s["total_scrolls"],
            "spm": s["spm"],
            "pages": s["pages"] or [],
            "referrer_domain": s["referrer_domain"] or "",
        })

    return JsonResponse({
        "client": {
            "device_type": client.device_type or "—",
            "browser": client.browser or "—",
            "os": client.os or "—",
            "country": format_country(client.country, client.country_name),
            "city": client.city or "—",
            "first_seen": timezone.localtime(client.first_seen).strftime("%d.%m.%Y %H:%M"),
            "is_bot": client.is_bot,
            "bot_name": client.bot_name or "",
        },
        "sessions": history,
    })
