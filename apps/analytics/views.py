from datetime import timedelta

from django.contrib.admin import site as admin_site
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .models import Session
from .utils import country_flag, format_duration


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
            "pages": s.pages or [],
            "scrolls": s.total_scrolls,
        })

    # Build hour labels: from 24h ago to now
    now_local = timezone.localtime(now)
    labels = []
    for i in range(25):
        t = now_local - timedelta(hours=24 - i)
        labels.append(t.strftime("%H"))

    return JsonResponse({
        "clients": list(clients_map.values()),
        "hour_labels": labels,
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
            bots_map[name] = {"name": name, "count": 0, "hits": []}

        bots_map[name]["count"] += 1
        start_ago = (now - started_at).total_seconds() / 3600
        bots_map[name]["hits"].append(round(24 - min(24, start_ago), 3))

    bots_list = sorted(bots_map.values(), key=lambda b: b["count"], reverse=True)

    # Build hour labels
    now_local = timezone.localtime(now)
    labels = []
    for i in range(25):
        t = now_local - timedelta(hours=24 - i)
        labels.append(t.strftime("%H"))

    return JsonResponse({
        "bots": bots_list,
        "hour_labels": labels,
    })
