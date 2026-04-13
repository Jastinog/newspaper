import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.billing.models import APIUsage


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

    # === KPI cards (money only) ===
    total_cost = APIUsage.objects.aggregate(t=Sum("cost_usd"))["t"] or Decimal("0")
    today_cost = (
        APIUsage.objects.filter(created_at__date=today)
        .aggregate(t=Sum("cost_usd"))["t"]
        or Decimal("0")
    )

    # === Daily cost chart (last 30 days) ===
    daily_usage = (
        APIUsage.objects.filter(created_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(cost=Sum("cost_usd"))
        .order_by("day")
    )
    days_map = {r["day"]: float(r["cost"]) for r in daily_usage}

    cost_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Cost ($)",
            "data": [days_map.get(d, 0) for d in dates],
            "backgroundColor": "rgba(99, 102, 241, 0.5)",
            "borderColor": "rgb(99, 102, 241)",
            "borderWidth": 2,
            "type": "bar",
        }],
    })

    context.update({
        "total_cost": f"${total_cost:.4f}",
        "today_cost": f"${today_cost:.4f}",
        "cost_chart": cost_chart,
    })
    return context
