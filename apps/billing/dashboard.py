import json
import re
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractHour
from django.utils import timezone

from apps.analytics.models import Activity, Client, Session
from apps.billing.models import APIUsage
from apps.feed.models import Article, Feed
from apps.research.models import Research
from apps.digest.models import Digest


_DEFAULT_COLOR = ("rgb(156, 163, 175)", "rgba(156, 163, 175, 0.5)")


def _build_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def _daily_series(day_map, dates, field, default=0):
    """Extract a single field from a date-keyed dict for each date."""
    return [day_map.get(str(d), {}).get(field, default) for d in dates]


def dashboard_callback(request, context):
    now = timezone.now()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)
    dates = _build_labels(now, 30)
    labels = [d.strftime("%d.%m") for d in dates]
    service_choices = dict(APIUsage.Service.choices)

    # === KPI cards ===
    total_cost = APIUsage.objects.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    total_tokens = APIUsage.objects.aggregate(t=Sum("total_tokens"))["t"] or 0
    today_qs = APIUsage.objects.filter(created_at__date=today)
    today_cost = today_qs.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    today_tokens = today_qs.aggregate(t=Sum("total_tokens"))["t"] or 0

    # Counts
    total_articles = Article.objects.count()
    total_feeds = Feed.objects.filter(enabled=True).count()
    total_digests = Digest.objects.count()
    total_researches = Research.objects.count()

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
    model_stats = [
        {
            "model": row["model"],
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "prompt": f"{row['prompt']:,}",
            "completion": f"{row['completion']:,}",
            "calls": row["calls"],
        }
        for row in by_model
    ]

    # === Breakdown by service (all time) ===
    by_service = (
        APIUsage.objects.values("service")
        .annotate(cost=Sum("cost_usd"), tokens=Sum("total_tokens"), calls=Count("id"))
        .order_by("service")
    )
    service_stats = [
        {
            "service": service_choices.get(row["service"], row["service"]),
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "calls": row["calls"],
        }
        for row in by_service
    ]

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
    service_model_stats = [
        {
            "service": service_choices.get(row["service"], row["service"]),
            "model": row["model"],
            "cost": f"${row['cost']:.4f}",
            "tokens": f"{row['tokens']:,}",
            "prompt": f"{row['prompt']:,}",
            "completion": f"{row['completion']:,}",
            "calls": row["calls"],
        }
        for row in by_service_model
    ]

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
            "data": _daily_series(days_map, dates, "cost"),
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
            "data": _daily_series(days_map, dates, "tokens"),
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
        "research": ("rgb(236, 72, 153)", "rgba(236, 72, 153, 0.5)"),
        "embedding": ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.5)"),
    }

    svc_days = {}
    for row in service_daily:
        svc = row["service"]
        svc_days.setdefault(svc, {})[str(row["day"])] = float(row["cost"])

    service_chart_datasets = []
    for svc, data in svc_days.items():
        border, bg = service_colors.get(svc, _DEFAULT_COLOR)
        service_chart_datasets.append({
            "label": service_choices.get(svc, svc),
            "data": [data.get(str(d), 0) for d in dates],
            "backgroundColor": bg,
            "borderColor": border,
            "borderWidth": 1,
        })

    service_chart = json.dumps({
        "labels": labels,
        "datasets": service_chart_datasets,
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

    model_cost_datasets = []
    for mdl, data in mdl_cost_days.items():
        border, bg = model_colors.get(mdl, _DEFAULT_COLOR)
        model_cost_datasets.append({
            "label": mdl,
            "data": [data.get(str(d), 0) for d in dates],
            "backgroundColor": bg,
            "borderColor": border,
            "borderWidth": 1,
        })

    model_cost_chart = json.dumps({
        "labels": labels,
        "datasets": model_cost_datasets,
    })

    model_token_datasets = []
    for mdl, data in mdl_token_days.items():
        border, bg = model_colors.get(mdl, _DEFAULT_COLOR)
        model_token_datasets.append({
            "label": mdl,
            "data": [data.get(str(d), 0) for d in dates],
            "borderColor": border,
            "backgroundColor": bg,
            "borderWidth": 2,
            "fill": True,
            "tension": 0.3,
        })

    model_token_chart = json.dumps({
        "labels": labels,
        "datasets": model_token_datasets,
    })

    # === Traffic analytics ===
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    base_pv = Activity.objects.filter(type=Activity.ActivityType.PAGE_VIEW)

    today_pv = base_pv.filter(timestamp__gte=today_start)
    yesterday_pv = base_pv.filter(timestamp__gte=yesterday_start, timestamp__lt=today_start)

    bot_pv_filter = Q(session__client__is_bot=True)

    today_views = today_pv.count()
    today_bot_views = today_pv.filter(bot_pv_filter).count()
    today_human_views = today_views - today_bot_views
    today_visitors = today_pv.values("session__client").distinct().count()
    today_bot_visitors = today_pv.filter(bot_pv_filter).values("session__client").distinct().count()
    today_human_visitors = today_visitors - today_bot_visitors

    yesterday_views = yesterday_pv.count()
    yesterday_visitors = yesterday_pv.values("session__client").distinct().count()

    # Hourly traffic for today — split by human/bot
    hourly_qs = list(
        today_pv
        .annotate(hour=ExtractHour("timestamp"))
        .values("hour")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=bot_pv_filter),
        )
        .order_by("hour")
    )
    hourly_map = {r["hour"]: r for r in hourly_qs}
    current_hour = now.hour
    hourly_labels = [f"{h}:00" for h in range(current_hour + 1)]

    hourly_human_data = []
    hourly_bot_data = []
    for h in range(current_hour + 1):
        row = hourly_map.get(h, {})
        bot = row.get("bot_views", 0)
        hourly_bot_data.append(bot)
        hourly_human_data.append(row.get("views", 0) - bot)

    hourly_chart = json.dumps({
        "labels": hourly_labels,
        "datasets": [
            {
                "label": "Humans",
                "data": hourly_human_data,
                "backgroundColor": "rgba(34, 197, 94, 0.5)",
                "borderColor": "rgb(34, 197, 94)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "traffic",
            },
            {
                "label": "Bots",
                "data": hourly_bot_data,
                "backgroundColor": "rgba(193, 18, 31, 0.4)",
                "borderColor": "rgb(193, 18, 31)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "traffic",
            },
        ],
    })

    # Daily views chart (last 30 days) — split by human/bot
    daily_views = (
        base_pv.filter(timestamp__gte=thirty_days_ago)
        .extra(select={"day": "DATE(timestamp)"})
        .values("day")
        .annotate(
            views=Count("id"),
            bot_views=Count("id", filter=bot_pv_filter),
            visitors=Count("session__client", distinct=True),
        )
        .order_by("day")
    )
    views_map = {str(r["day"]): r for r in daily_views}

    daily_human_views = []
    daily_bot_views = []
    daily_visitors = []
    for d in dates:
        row = views_map.get(str(d), {})
        bot = row.get("bot_views", 0)
        daily_bot_views.append(bot)
        daily_human_views.append(row.get("views", 0) - bot)
        daily_visitors.append(row.get("visitors", 0))

    views_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Human Views",
                "data": daily_human_views,
                "borderColor": "rgb(34, 197, 94)",
                "backgroundColor": "rgba(34, 197, 94, 0.1)",
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            },
            {
                "label": "Bot Views",
                "data": daily_bot_views,
                "borderColor": "rgb(193, 18, 31)",
                "backgroundColor": "rgba(193, 18, 31, 0.08)",
                "borderWidth": 2,
                "borderDash": [4, 4],
                "fill": True,
                "tension": 0.3,
            },
            {
                "label": "Clients",
                "data": daily_visitors,
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
        Client.objects.filter(last_seen__gte=thirty_days_ago, is_bot=False)
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
            "label": "Clients",
            "data": [r["count"] for r in top_os],
            "backgroundColor": os_palette[:len(top_os)],
            "borderWidth": 0,
            "type": "bar",
        }],
    })

    # Top referrers
    top_referrers = list(
        Session.objects.filter(started_at__gte=thirty_days_ago)
        .exclude(referrer_domain="")
        .values("referrer_domain")
        .annotate(sessions=Count("id"))
        .order_by("-sessions")[:8]
    )

    # === Top Researches by views ===
    research_views = list(
        base_pv.filter(timestamp__gte=thirty_days_ago, view_name="research")
        .values("path")
        .annotate(views=Count("id"))
        .order_by("-views")[:10]
    )
    # Extract item_id from path like /research/123/
    item_ids_map = {}
    for row in research_views:
        m = re.search(r"/research/(\d+)/", row["path"])
        if m:
            item_ids_map[int(m.group(1))] = row["views"]

    top_researches = []
    if item_ids_map:
        dives = (
            Research.objects
            .filter(item_id__in=item_ids_map.keys())
            .select_related("item__section__digest")
        )
        for dive in dives:
            top_researches.append({
                "title": dive.title[:80],
                "views": item_ids_map.get(dive.item_id, 0),
                "item_id": dive.item_id,
                "date": dive.created_at.strftime("%d.%m"),
            })
        top_researches.sort(key=lambda x: x["views"], reverse=True)

    # === Recent API calls table ===
    recent_calls = (
        APIUsage.objects.select_related("digest", "research")
        .order_by("-created_at")[:15]
    )
    recent_table = [
        {
            "date": u.created_at.strftime("%d.%m %H:%M"),
            "service": service_choices.get(u.service, u.service),
            "model": u.model,
            "tokens": f"{u.total_tokens:,}",
            "cost": f"${u.cost_usd:.4f}",
        }
        for u in recent_calls
    ]

    context.update({
        "total_cost": f"${total_cost:.4f}",
        "total_tokens": f"{total_tokens:,}",
        "today_cost": f"${today_cost:.4f}",
        "today_tokens": f"{today_tokens:,}",
        "total_articles": f"{total_articles:,}",
        "total_feeds": total_feeds,
        "total_digests": total_digests,
        "total_researches": total_researches,
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
        "today_human_views": f"{today_human_views:,}",
        "today_bot_views": f"{today_bot_views:,}",
        "today_visitors": f"{today_visitors:,}",
        "today_human_visitors": f"{today_human_visitors:,}",
        "today_bot_visitors": f"{today_bot_visitors:,}",
        "yesterday_views": f"{yesterday_views:,}",
        "yesterday_visitors": f"{yesterday_visitors:,}",
        "hourly_chart": hourly_chart,
        "views_chart": views_chart,
        "os_chart": os_chart,
        "top_referrers": top_referrers,
        "top_researches": top_researches,
    })
    return context
