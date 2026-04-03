from datetime import timedelta

from django.db.models import Count, Q
from django.contrib.admin import site as admin_site
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .dashboard import build_analytics_context
from .models import Activity, Client, Session
from .utils import country_flag, format_duration


@staff_member_required
def analytics_dashboard(request):
    context = {**admin_site.each_context(request), "title": "Analytics Dashboard"}
    context.update(build_analytics_context(request))
    return render(request, "admin/analytics_dashboard.html", context)


@staff_member_required
def analytics_dashboard_api(request):
    return JsonResponse(build_analytics_context(request))


@staff_member_required
def visitors_api(request):
    """Return client list with sessions for the Visitors tab (lazy-loaded)."""
    days = min(max(int(request.GET.get("days", 30)), 1), 90)
    since = timezone.now() - timedelta(days=days)

    clients = list(
        Client.objects.filter(is_bot=False, last_seen__gte=since)
        .annotate(
            session_count=Count(
                "session", filter=Q(session__is_human=True, session__started_at__gte=since),
            ),
        )
        .filter(session_count__gt=0)
        .order_by("-last_seen")[:100]
    )

    client_ids = [c.pk for c in clients]

    sessions = list(
        Session.objects.filter(
            client_id__in=client_ids, is_human=True, started_at__gte=since,
        )
        .order_by("-started_at")
    )
    sessions_by_client = {}
    for s in sessions:
        sessions_by_client.setdefault(s.client_id, []).append(s)

    session_ids = [s.pk for s in sessions]
    activities = list(
        Activity.objects.filter(session_id__in=session_ids)
        .filter(type__in=[
            Activity.ActivityType.PAGE_VIEW,
            Activity.ActivityType.SCROLL,
            Activity.ActivityType.CLICK,
        ])
        .order_by("timestamp")
    )
    activities_by_session = {}
    for a in activities:
        activities_by_session.setdefault(a.session_id, []).append(a)

    TYPE_LABELS = {
        Activity.ActivityType.PAGE_VIEW: "page_view",
        Activity.ActivityType.SCROLL: "scroll",
        Activity.ActivityType.CLICK: "click",
    }

    result = []
    for c in clients:
        c_sessions = sessions_by_client.get(c.pk, [])
        sessions_out = []
        for s in c_sessions:
            acts = activities_by_session.get(s.pk, [])
            sessions_out.append({
                "id": s.pk,
                "started": timezone.localtime(s.started_at).strftime("%d.%m %H:%M"),
                "duration": format_duration(s.active_time),
                "pages": s.page_count,
                "referrer": s.referrer_domain or "",
                "activities": [
                    {
                        "type": TYPE_LABELS.get(a.type, a.type),
                        "path": a.path,
                        "time": timezone.localtime(a.timestamp).strftime("%H:%M:%S"),
                    }
                    for a in acts
                ],
            })
        result.append({
            "id": c.pk,
            "device": c.device_type or "?",
            "browser": c.browser or "?",
            "os": c.os or "?",
            "country": country_flag(c.country),
            "country_name": c.country_name or "",
            "city": c.city or "",
            "last_seen": timezone.localtime(c.last_seen).strftime("%d.%m %H:%M"),
            "sessions": sessions_out,
            "session_count": len(c_sessions),
            "total_pages": sum(s.page_count for s in c_sessions),
            "total_time": format_duration(sum(s.active_time for s in c_sessions)),
        })

    return JsonResponse({"clients": result})


@staff_member_required
def traffic_graph_api(request):
    """Return traffic graph data: country -> city -> client (humans only)."""
    days = min(max(int(request.GET.get("days", 7)), 1), 30)
    since = timezone.now() - timedelta(days=days)

    rows = list(
        Session.objects.filter(started_at__gte=since, client__is_bot=False)
        .select_related("client")
        .order_by("-started_at")
    )

    tree = {}
    for s in rows:
        c = s.client
        code = c.country or "??"
        city_name = c.city or "Unknown"

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
            "sc": 0,
            "pages": 0,
            "time": 0,
        })
        cl["sc"] += 1
        cl["pages"] += s.page_count
        cl["time"] += s.active_time

    countries_out = []
    for _code, co in sorted(tree.items(), key=lambda x: x[1]["n"], reverse=True):
        cities_out = []
        for ci_name, ci in sorted(co["cities"].items(), key=lambda x: x[1]["n"], reverse=True):
            clients_out = []
            for cl in sorted(ci["clients"].values(), key=lambda x: x["sc"], reverse=True):
                clients_out.append({
                    "browser": cl["browser"],
                    "os": cl["os"],
                    "device": cl["device"],
                    "sc": cl["sc"],
                    "pages": cl["pages"],
                    "time": format_duration(cl["time"]),
                    "url": reverse("admin:analytics_client_change", args=[cl["id"]]),
                })
            cities_out.append({
                "name": ci_name,
                "sc": ci["n"],
                "cc": len(ci["clients"]),
                "clients": clients_out,
            })
        countries_out.append({
            "flag": co["flag"],
            "name": co["name"],
            "sc": co["n"],
            "cc": len(co["cities"]),
            "cities": cities_out,
        })

    return JsonResponse({"countries": countries_out, "days": days})


@staff_member_required
def session_graph_api(request):
    """Return force-graph data: country → city → day → session nodes with links."""
    days = min(max(int(request.GET.get("days", 30)), 1), 90)
    now = timezone.now()
    since = now - timedelta(days=days)

    # Fetch sessions with client info (humans only)
    sessions = list(
        Session.objects.filter(started_at__gte=since, client__is_bot=False, active_time__gte=60)
        .exclude(client__country="")
        .select_related("client")
        .order_by("-active_time")
    )

    # Group by city+date, keep top 5 longest per day
    day_buckets: dict[str, list] = {}
    for s in sessions:
        c = s.client
        code = c.country or "??"
        city_name = c.city or "Unknown"
        local_dt = timezone.localtime(s.started_at)
        key = f"{code}_{city_name}_{local_dt.date().isoformat()}"
        bucket = day_buckets.setdefault(key, [])
        if len(bucket) < 5:
            bucket.append(s)
    sessions = [s for bucket in day_buckets.values() for s in bucket]

    # Build nodes + links
    nodes = []
    links = []
    country_nodes = {}  # code -> node dict
    city_nodes = {}     # "code_city" -> node dict
    day_nodes = {}      # "city_key_YYYY-MM-DD" -> node dict

    # Compute time range for normalizing day age (0 = today, 1 = oldest)
    total_days = days or 1
    today = timezone.localtime(now).date()

    for s in sessions:
        c = s.client
        code = c.country or "??"
        country_name = c.country_name or code
        city_name = c.city or "Unknown"
        local_dt = timezone.localtime(s.started_at)
        session_date = local_dt.date()

        # Country node (deduplicated)
        if code not in country_nodes:
            co_node = {
                "id": f"co_{code}",
                "type": "country",
                "label": f"{country_flag(code)} {country_name}",
                "sessions": 0,
            }
            country_nodes[code] = co_node
            nodes.append(co_node)
        country_nodes[code]["sessions"] += 1

        # City node (deduplicated)
        city_key = f"{code}_{city_name}"
        if city_key not in city_nodes:
            ci_node = {
                "id": f"ci_{city_key}",
                "type": "city",
                "label": city_name,
                "sessions": 0,
            }
            city_nodes[city_key] = ci_node
            nodes.append(ci_node)
            links.append({
                "source": country_nodes[code]["id"],
                "target": ci_node["id"],
            })
        city_nodes[city_key]["sessions"] += 1

        # Day node (deduplicated per city+date)
        day_key = f"{city_key}_{session_date.isoformat()}"
        if day_key not in day_nodes:
            day_age = (today - session_date).days / total_days
            day_age = max(0.0, min(1.0, day_age))
            day_node = {
                "id": f"d_{day_key}",
                "type": "day",
                "label": local_dt.strftime("%d.%m"),
                "sessions": 0,
                "age": round(day_age, 4),
            }
            day_nodes[day_key] = day_node
            nodes.append(day_node)
            links.append({
                "source": city_nodes[city_key]["id"],
                "target": day_node["id"],
            })
        day_nodes[day_key]["sessions"] += 1

        sid = f"s_{s.id}"
        nodes.append({
            "id": sid,
            "type": "session",
            "time": format_duration(s.active_time),
            "hour": local_dt.strftime("%H:%M"),
            "age": day_nodes[day_key]["age"],
        })
        links.append({
            "source": day_nodes[day_key]["id"],
            "target": sid,
        })

    return JsonResponse({"nodes": nodes, "links": links, "days": days})
