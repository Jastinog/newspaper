import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.news.models import APIUsage, Article, DeepDive, Digest, Feed


def dashboard_callback(request, context):
    now = timezone.now()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)

    # === KPI cards ===
    total_cost = APIUsage.objects.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    total_tokens = APIUsage.objects.aggregate(t=Sum("total_tokens"))["t"] or 0
    today_cost = (
        APIUsage.objects.filter(created_at__date=today)
        .aggregate(t=Sum("cost_usd"))["t"]
        or Decimal("0")
    )
    today_tokens = (
        APIUsage.objects.filter(created_at__date=today)
        .aggregate(t=Sum("total_tokens"))["t"]
        or 0
    )

    # Counts
    total_articles = Article.objects.count()
    total_feeds = Feed.objects.filter(enabled=True).count()
    total_digests = Digest.objects.count()
    total_deep_dives = DeepDive.objects.count()

    # === Cost by service (all time) ===
    by_service = (
        APIUsage.objects.values("service")
        .annotate(cost=Sum("cost_usd"), tokens=Sum("total_tokens"), calls=Count("id"))
        .order_by("service")
    )
    service_stats = []
    for row in by_service:
        label = dict(APIUsage.Service.choices).get(row["service"], row["service"])
        service_stats.append({
            "service": label,
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "calls": row["calls"],
        })

    # === Daily cost chart (last 30 days) ===
    daily_usage = (
        APIUsage.objects.filter(created_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(created_at)"})
        .values("day")
        .annotate(cost=Sum("cost_usd"), tokens=Sum("total_tokens"))
        .order_by("day")
    )

    days_map = {}
    for row in daily_usage:
        days_map[str(row["day"])] = {
            "cost": float(row["cost"]),
            "tokens": row["tokens"],
        }

    labels = []
    cost_data = []
    token_data = []
    for i in range(30):
        d = (now - timedelta(days=29 - i)).date()
        day_str = str(d)
        labels.append(d.strftime("%d.%m"))
        cost_data.append(days_map.get(day_str, {}).get("cost", 0))
        token_data.append(days_map.get(day_str, {}).get("tokens", 0))

    cost_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Cost ($)",
                "data": cost_data,
                "backgroundColor": "rgba(99, 102, 241, 0.5)",
                "borderColor": "rgb(99, 102, 241)",
                "borderWidth": 2,
                "type": "bar",
            },
        ],
    })

    token_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Tokens",
                "data": token_data,
                "borderColor": "rgb(234, 179, 8)",
                "backgroundColor": "rgba(234, 179, 8, 0.1)",
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            },
        ],
    })

    # === Daily cost by service chart (last 30 days) ===
    service_daily = (
        APIUsage.objects.filter(created_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(created_at)"})
        .values("day", "service")
        .annotate(cost=Sum("cost_usd"))
        .order_by("day")
    )

    service_colors = {
        "digest": ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.5)"),
        "deep_dive": ("rgb(236, 72, 153)", "rgba(236, 72, 153, 0.5)"),
        "embedding": ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.5)"),
    }

    service_days = {}
    for row in service_daily:
        svc = row["service"]
        if svc not in service_days:
            service_days[svc] = {}
        service_days[svc][str(row["day"])] = float(row["cost"])

    service_datasets = []
    for svc, svc_data in service_days.items():
        border, bg = service_colors.get(svc, ("rgb(156, 163, 175)", "rgba(156, 163, 175, 0.5)"))
        label = dict(APIUsage.Service.choices).get(svc, svc)
        data = [svc_data.get(str((now - timedelta(days=29 - i)).date()), 0) for i in range(30)]
        service_datasets.append({
            "label": label,
            "data": data,
            "backgroundColor": bg,
            "borderColor": border,
            "borderWidth": 1,
        })

    service_chart = json.dumps({
        "labels": labels,
        "datasets": service_datasets,
    })

    # === Recent API calls table ===
    recent_calls = (
        APIUsage.objects.select_related("digest", "deep_dive")
        .order_by("-created_at")[:15]
    )
    recent_table = []
    for u in recent_calls:
        recent_table.append({
            "date": u.created_at.strftime("%d.%m %H:%M"),
            "service": dict(APIUsage.Service.choices).get(u.service, u.service),
            "model": u.model,
            "tokens": f"{u.total_tokens:,}",
            "cost": f"${u.cost_usd:.4f}",
        })

    context.update({
        "total_cost": f"${total_cost:.4f}",
        "total_tokens": f"{total_tokens:,}",
        "today_cost": f"${today_cost:.4f}",
        "today_tokens": f"{today_tokens:,}",
        "total_articles": f"{total_articles:,}",
        "total_feeds": total_feeds,
        "total_digests": total_digests,
        "total_deep_dives": total_deep_dives,
        "service_stats": service_stats,
        "cost_chart": cost_chart,
        "token_chart": token_chart,
        "service_chart": service_chart,
        "recent_table": recent_table,
    })
    return context
