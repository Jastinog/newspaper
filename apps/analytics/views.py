from datetime import date, datetime, timedelta

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
    """Return 24-hour timeline data: clients with their sessions for a given date."""
    # Parse date param (default: today)
    date_str = request.GET.get("date")
    if date_str:
        try:
            selected_date = date.fromisoformat(date_str)
        except ValueError:
            selected_date = timezone.localdate()
    else:
        selected_date = timezone.localdate()

    # Build datetime range for the selected date (DST-safe)
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(selected_date, datetime.min.time()), tz)
    day_end = day_start + timedelta(days=1)

    # Fetch human WS sessions for the day
    sessions = list(
        Session.objects.filter(
            started_at__gte=day_start,
            started_at__lt=day_end,
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
            city = c.city or ""
            label_parts = [p for p in [flag, city, c.browser, c.os] if p]
            clients_map[c.pk] = {
                "id": c.pk,
                "label": " / ".join(label_parts) or f"Client {c.pk}",
                "sessions": [],
            }

        # Convert times to fractional hours (0..24)
        local_start = timezone.localtime(s.started_at)
        start_h = local_start.hour + local_start.minute / 60 + local_start.second / 3600

        if s.ended_at:
            local_end = timezone.localtime(s.ended_at)
        elif s.last_ping_at:
            local_end = timezone.localtime(s.last_ping_at)
        else:
            local_end = local_start

        end_h = local_end.hour + local_end.minute / 60 + local_end.second / 3600
        # Ensure minimum visible width
        if end_h <= start_h:
            end_h = start_h + 0.05

        clients_map[c.pk]["sessions"].append({
            "start": round(start_h, 3),
            "end": round(end_h, 3),
            "duration": format_duration(s.active_time),
            "spm": s.spm,
            "pages": s.pages or [],
            "scrolls": s.total_scrolls,
        })

    return JsonResponse({
        "date": selected_date.isoformat(),
        "clients": list(clients_map.values()),
    })
