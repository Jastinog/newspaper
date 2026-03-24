from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from .models import Session
from .utils import country_flag, format_duration


@staff_member_required
def traffic_graph_api(request):
    """Return traffic graph data: sources -> clients -> sessions."""
    days = min(max(int(request.GET.get("days", 7)), 1), 30)
    since = timezone.now() - timedelta(days=days)

    rows = list(
        Session.objects.filter(started_at__gte=since)
        .select_related("client")
        .order_by("-started_at")[:500]
    )

    src_map = {}
    for s in rows:
        dom = s.referrer_domain or "direct"
        c = s.client

        bucket = src_map.setdefault(dom, {"n": 0, "clients": {}})
        bucket["n"] += 1

        cd = bucket["clients"].setdefault(c.id, {
            "id": c.id,
            "browser": c.browser or "?",
            "os": c.os or "?",
            "country": c.country,
            "city": c.city,
            "country_name": c.country_name,
            "is_bot": c.is_bot,
            "bot_name": c.bot_name,
            "sessions": [],
        })
        cd["sessions"].append({
            "id": s.id,
            "pages": s.page_count,
            "time": format_duration(s.active_time),
            "date": s.started_at.strftime("%d.%m %H:%M"),
            "ok": s.has_interaction,
        })

    # Top 8 sources, top 5 clients each, top 3 sessions each
    top = sorted(src_map.items(), key=lambda x: x[1]["n"], reverse=True)[:8]
    sources = []
    for dom, data in top:
        clients = sorted(
            data["clients"].values(),
            key=lambda c: len(c["sessions"]),
            reverse=True,
        )[:5]
        for cd in clients:
            flag = country_flag(cd["country"])
            cd["loc"] = " ".join(filter(None, [flag, cd["city"] or cd["country_name"]]))
            cd["sc"] = len(cd["sessions"])
            cd["sessions"] = cd["sessions"][:3]
            cd["url"] = reverse("admin:analytics_client_change", args=[cd["id"]])
            for k in ("country", "city", "country_name"):
                cd.pop(k, None)
        sources.append({
            "domain": dom,
            "sessions": data["n"],
            "clients_total": len(data["clients"]),
            "clients": clients,
        })

    return JsonResponse({"sources": sources, "days": days})
