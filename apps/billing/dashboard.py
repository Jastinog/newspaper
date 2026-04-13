import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.billing.models import APIUsage


# Stable palette — assigned by insertion order when a model isn't pre-mapped.
_MODEL_COLORS = {
    "gpt-4.1-mini": "99, 102, 241",          # indigo
    "gpt-4.1": "168, 85, 247",               # purple
    "gpt-4o-mini": "59, 130, 246",           # blue
    "gpt-4o": "14, 165, 233",                # sky
    "text-embedding-3-small": "34, 197, 94",  # green
    "text-embedding-3-large": "16, 185, 129", # emerald
}
_FALLBACK_PALETTE = [
    "244, 114, 182",  # pink
    "251, 146, 60",   # orange
    "234, 179, 8",    # amber
    "20, 184, 166",   # teal
    "139, 92, 246",   # violet
    "239, 68, 68",    # red
]


def _build_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def _color_for(model, fallback_idx):
    rgb = _MODEL_COLORS.get(model)
    if rgb is None:
        rgb = _FALLBACK_PALETTE[fallback_idx % len(_FALLBACK_PALETTE)]
    return f"rgb({rgb})", f"rgba({rgb}, 0.15)"


def dashboard_callback(request, context):
    now = timezone.now()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)
    dates = _build_labels(now, 30)
    labels = [d.strftime("%d.%m") for d in dates]

    # === KPI cards (money only) ===
    total_cost = APIUsage.objects.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    today_cost = (
        APIUsage.objects.filter(created_at__date=today)
        .aggregate(t=Sum("cost_usd"))["t"]
        or Decimal("0")
    )

    # === Daily cost per model (last 30 days) ===
    per_model = (
        APIUsage.objects.filter(created_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day", "model")
        .annotate(cost=Sum("cost_usd"))
        .order_by("model", "day")
    )

    # { model: { date: cost } }
    model_day_cost: dict[str, dict] = {}
    for row in per_model:
        model_day_cost.setdefault(row["model"], {})[row["day"]] = float(row["cost"])

    datasets = []
    total_per_day = [0.0] * len(dates)

    # Stable ordering: descending total spend, so biggest spender draws first.
    ordered_models = sorted(
        model_day_cost,
        key=lambda m: sum(model_day_cost[m].values()),
        reverse=True,
    )

    for idx, model in enumerate(ordered_models):
        day_map = model_day_cost[model]
        series = [day_map.get(d, 0.0) for d in dates]
        for i, v in enumerate(series):
            total_per_day[i] += v
        border, bg = _color_for(model, idx)
        datasets.append({
            "label": model,
            "data": series,
            "borderColor": border,
            "backgroundColor": bg,
            "borderWidth": 1,
            "tension": 0.3,
            "fill": False,
            "pointRadius": 0,
            "pointHoverRadius": 4,
        })

    # Total line — drawn on top, bolder. Bright amber stays visible on both
    # dark and light themes (the unfold default near-black would disappear in
    # dark mode).
    datasets.append({
        "label": "Total",
        "data": total_per_day,
        "borderColor": "rgb(250, 204, 21)",
        "backgroundColor": "rgba(250, 204, 21, 0.12)",
        "borderWidth": 2,
        "borderDash": [6, 4],
        "tension": 0.3,
        "fill": False,
        "pointRadius": 0,
        "pointHoverRadius": 5,
        "displayYAxis": True,
    })

    cost_chart = json.dumps({
        "labels": labels,
        "datasets": datasets,
    })

    context.update({
        "total_cost": f"${total_cost:.4f}",
        "today_cost": f"${today_cost:.4f}",
        "cost_chart": cost_chart,
    })
    return context
