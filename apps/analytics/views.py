from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from .models import Session
from .utils import country_flag, format_duration


@staff_member_required
def traffic_graph_api(request):
    """Return traffic graph data: country -> city -> client -> sessions (humans only)."""
    days = min(max(int(request.GET.get("days", 7)), 1), 30)
    since = timezone.now() - timedelta(days=days)

    rows = list(
        Session.objects.filter(started_at__gte=since, client__is_bot=False)
        .select_related("client")
        .order_by("-started_at")
    )

    # Build tree: country → city → client → sessions
    tree = {}
    for s in rows:
        c = s.client
        code = c.country or "??"
        city_name = c.city or "?"

        country = tree.setdefault(code, {
            "name": c.country_name or code,
            "flag": country_flag(code),
            "n": 0,
            "cities": {},
        })
        country["n"] += 1

        city = country["cities"].setdefault(city_name, {"n": 0, "clients": {}})
        city["n"] += 1

        cl = city["clients"].setdefault(c.id, {
            "id": c.id,
            "browser": c.browser or "?",
            "os": c.os or "?",
            "device": c.device_type or "?",
            "sessions": [],
        })
        cl["sessions"].append({
            "id": s.id,
            "pages": s.page_count,
            "time": format_duration(s.active_time),
            "date": s.started_at.strftime("%d.%m %H:%M"),
            "ref": s.referrer_domain or "",
            "ok": s.has_interaction,
            "url": reverse("admin:analytics_session_change", args=[s.id]),
        })

    countries_out = []
    for _code, co in sorted(tree.items(), key=lambda x: x[1]["n"], reverse=True):
        cities_out = []
        for ci_name, ci in sorted(co["cities"].items(), key=lambda x: x[1]["n"], reverse=True):
            clients_out = []
            for cl in sorted(ci["clients"].values(), key=lambda x: len(x["sessions"]), reverse=True):
                clients_out.append({
                    "browser": cl["browser"],
                    "os": cl["os"],
                    "device": cl["device"],
                    "sc": len(cl["sessions"]),
                    "url": reverse("admin:analytics_client_change", args=[cl["id"]]),
                    "sessions": cl["sessions"][:5],
                })
            cities_out.append({
                "name": ci_name,
                "cc": len(ci["clients"]),
                "clients": clients_out,
            })
        countries_out.append({
            "flag": co["flag"],
            "name": co["name"],
            "cc": len(co["cities"]),
            "cities": cities_out,
        })

    return JsonResponse({"countries": countries_out, "days": days})
