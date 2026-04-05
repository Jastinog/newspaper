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
            city = (c.city or "")[:6].ljust(6)
            label = f"{flag} {city}" if flag else city
            clients_map[c.pk] = {
                "id": c.pk,
                "label": label.strip() or f"Client {c.pk}",
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
