import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import ExtractHour
from django.utils import timezone

from apps.analytics.models import PageView
import re

from apps.news.models import APIUsage, Article, DeepDive, Digest, Feed


def _build_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def dashboard_callback(request, context):
    now = timezone.now()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)
    dates = _build_labels(now, 30)
    labels = [d.strftime("%d.%m") for d in dates]

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

    # === Breakdown by model (all time) ===
    by_model = (
        APIUsage.objects.values("model")
        .annotate(
            cost=Sum("cost_usd"),
            tokens=Sum("total_tokens"),
            prompt=Sum("prompt_tokens"),
            completion=Sum("completion_tokens"),
            calls=Count("id"),
        )
        .order_by("model")
    )
    model_stats = []
    for row in by_model:
        model_stats.append({
            "model": row["model"],
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "prompt": f"{row['prompt']:,}",
            "completion": f"{row['completion']:,}",
            "calls": row["calls"],
        })

    # === Breakdown by service (all time) ===
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

    # === Breakdown by service + model (all time) ===
    by_service_model = (
        APIUsage.objects.values("service", "model")
        .annotate(
            cost=Sum("cost_usd"),
            tokens=Sum("total_tokens"),
            prompt=Sum("prompt_tokens"),
            completion=Sum("completion_tokens"),
            calls=Count("id"),
        )
        .order_by("service", "model")
    )
    service_model_stats = []
    for row in by_service_model:
        label = dict(APIUsage.Service.choices).get(row["service"], row["service"])
        service_model_stats.append({
            "service": label,
            "model": row["model"],
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "prompt": f"{row['prompt']:,}",
            "completion": f"{row['completion']:,}",
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
    days_map = {str(r["day"]): {"cost": float(r["cost"]), "tokens": r["tokens"]} for r in daily_usage}

    cost_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Cost ($)",
            "data": [days_map.get(str(d), {}).get("cost", 0) for d in dates],
            "backgroundColor": "rgba(99, 102, 241, 0.5)",
            "borderColor": "rgb(99, 102, 241)",
            "borderWidth": 2,
            "type": "bar",
        }],
    })

    token_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Tokens",
            "data": [days_map.get(str(d), {}).get("tokens", 0) for d in dates],
            "borderColor": "rgb(234, 179, 8)",
            "backgroundColor": "rgba(234, 179, 8, 0.1)",
            "borderWidth": 2,
            "fill": True,
            "tension": 0.3,
        }],
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

    svc_days = {}
    for row in service_daily:
        svc = row["service"]
        svc_days.setdefault(svc, {})[str(row["day"])] = float(row["cost"])

    service_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": dict(APIUsage.Service.choices).get(svc, svc),
                "data": [data.get(str(d), 0) for d in dates],
                "backgroundColor": service_colors.get(svc, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[1],
                "borderColor": service_colors.get(svc, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[0],
                "borderWidth": 1,
            }
            for svc, data in svc_days.items()
        ],
    })

    # === Daily cost by model chart (last 30 days) ===
    model_daily = (
        APIUsage.objects.filter(created_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(created_at)"})
        .values("day", "model")
        .annotate(cost=Sum("cost_usd"), tokens=Sum("total_tokens"))
        .order_by("day")
    )

    model_colors = {
        "gpt-4.1-mini": ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.5)"),
        "gpt-4.1": ("rgb(168, 85, 247)", "rgba(168, 85, 247, 0.5)"),
        "gpt-4o-mini": ("rgb(59, 130, 246)", "rgba(59, 130, 246, 0.5)"),
        "gpt-4o": ("rgb(14, 165, 233)", "rgba(14, 165, 233, 0.5)"),
        "text-embedding-3-small": ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.5)"),
        "text-embedding-3-large": ("rgb(16, 185, 129)", "rgba(16, 185, 129, 0.5)"),
    }

    mdl_cost_days = {}
    mdl_token_days = {}
    for row in model_daily:
        m = row["model"]
        mdl_cost_days.setdefault(m, {})[str(row["day"])] = float(row["cost"])
        mdl_token_days.setdefault(m, {})[str(row["day"])] = row["tokens"]

    model_cost_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": mdl,
                "data": [data.get(str(d), 0) for d in dates],
                "backgroundColor": model_colors.get(mdl, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[1],
                "borderColor": model_colors.get(mdl, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[0],
                "borderWidth": 1,
            }
            for mdl, data in mdl_cost_days.items()
        ],
    })

    model_token_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": mdl,
                "data": [data.get(str(d), 0) for d in dates],
                "borderColor": model_colors.get(mdl, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[0],
                "backgroundColor": model_colors.get(mdl, ("rgb(156,163,175)", "rgba(156,163,175,0.5)"))[1],
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            }
            for mdl, data in mdl_token_days.items()
        ],
    })

    # === Traffic analytics ===
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    base_pv = PageView.objects.filter(is_bot=False)

    today_pv = base_pv.filter(timestamp__gte=today_start)
    yesterday_pv = base_pv.filter(timestamp__gte=yesterday_start, timestamp__lt=today_start)

    today_views = today_pv.count()
    today_visitors = today_pv.values("session_hash").distinct().count()
    yesterday_views = yesterday_pv.count()
    yesterday_visitors = yesterday_pv.values("session_hash").distinct().count()

    # Hourly traffic for today
    hourly_qs = list(
        today_pv
        .annotate(hour=ExtractHour("timestamp"))
        .values("hour")
        .annotate(views=Count("id"))
        .order_by("hour")
    )
    hourly_map = {r["hour"]: r["views"] for r in hourly_qs}
    current_hour = now.hour
    hourly_labels = [f"{h}:00" for h in range(current_hour + 1)]
    hourly_values = [hourly_map.get(h, 0) for h in range(current_hour + 1)]

    hourly_chart = json.dumps({
        "labels": hourly_labels,
        "datasets": [{
            "label": "Views",
            "data": hourly_values,
            "backgroundColor": "rgba(34, 197, 94, 0.5)",
            "borderColor": "rgb(34, 197, 94)",
            "borderWidth": 1,
            "type": "bar",
        }],
    })

    # Daily views chart (last 30 days)
    daily_views = (
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .extra(select={"day": "DATE(timestamp)"})
        .values("day")
        .annotate(views=Count("id"), visitors=Count("session_hash", distinct=True))
        .order_by("day")
    )
    views_map = {str(r["day"]): {"views": r["views"], "visitors": r["visitors"]} for r in daily_views}

    views_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Views",
                "data": [views_map.get(str(d), {}).get("views", 0) for d in dates],
                "borderColor": "rgb(34, 197, 94)",
                "backgroundColor": "rgba(34, 197, 94, 0.1)",
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            },
            {
                "label": "Visitors",
                "data": [views_map.get(str(d), {}).get("visitors", 0) for d in dates],
                "borderColor": "rgb(59, 130, 246)",
                "backgroundColor": "rgba(59, 130, 246, 0.1)",
                "borderWidth": 2,
                "borderDash": [5, 5],
                "fill": False,
                "tension": 0.3,
            },
        ],
    })

    # Top OS
    top_os = list(
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .exclude(os="")
        .values("os")
        .annotate(count=Count("id"))
        .order_by("-count")[:6]
    )
    os_palette = [
        "rgba(99,102,241,0.7)", "rgba(236,72,153,0.7)", "rgba(34,197,94,0.7)",
        "rgba(234,179,8,0.7)", "rgba(59,130,246,0.7)", "rgba(168,85,247,0.7)",
    ]
    os_chart = json.dumps({
        "labels": [r["os"] for r in top_os],
        "datasets": [{
            "label": "Views",
            "data": [r["count"] for r in top_os],
            "backgroundColor": os_palette[:len(top_os)],
            "borderWidth": 0,
            "type": "bar",
        }],
    })

    # Top referrers
    top_referrers = list(
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .exclude(referrer_domain="")
        .values("referrer_domain")
        .annotate(views=Count("id"))
        .order_by("-views")[:8]
    )

    # === Top Deep Dives by views ===
    deep_dive_views = list(
        base_pv.filter(timestamp__gte=thirty_days_ago, view_name="deep_dive")
        .values("path")
        .annotate(views=Count("id"))
        .order_by("-views")[:10]
    )
    # Extract item_id from path like /deep-dive/123/ or /en/deep-dive/123/
    item_ids_map = {}
    for row in deep_dive_views:
        m = re.search(r"/deep-dive/(\d+)/", row["path"])
        if m:
            item_ids_map[int(m.group(1))] = row["views"]

    top_deep_dives = []
    if item_ids_map:
        dives = (
            DeepDive.objects
            .filter(item_id__in=item_ids_map.keys())
            .select_related("item__section__digest")
        )
        for dive in dives:
            top_deep_dives.append({
                "title": dive.title[:80],
                "views": item_ids_map.get(dive.item_id, 0),
                "item_id": dive.item_id,
                "date": dive.created_at.strftime("%d.%m"),
            })
        top_deep_dives.sort(key=lambda x: x["views"], reverse=True)

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
        "model_stats": model_stats,
        "service_stats": service_stats,
        "service_model_stats": service_model_stats,
        "cost_chart": cost_chart,
        "token_chart": token_chart,
        "service_chart": service_chart,
        "model_cost_chart": model_cost_chart,
        "model_token_chart": model_token_chart,
        "recent_table": recent_table,
        # Traffic
        "today_views": f"{today_views:,}",
        "today_visitors": f"{today_visitors:,}",
        "yesterday_views": f"{yesterday_views:,}",
        "yesterday_visitors": f"{yesterday_visitors:,}",
        "hourly_chart": hourly_chart,
        "views_chart": views_chart,
        "os_chart": os_chart,
        "top_referrers": top_referrers,
        "top_deep_dives": top_deep_dives,
    })
    return context
