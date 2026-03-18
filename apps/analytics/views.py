from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .models import PageView


def _base_qs(request):
    """Base queryset: non-bot views within the requested period."""
    days = min(int(request.GET.get("days", 30)), 365)
    since = timezone.now() - timedelta(days=days)
    return PageView.objects.filter(is_bot=False, timestamp__gte=since)


# ── Dashboard page ─────────────────────────────────────────


@staff_member_required
def dashboard(request):
    return render(request, "analytics/dashboard.html")


# ── JSON API endpoints ─────────────────────────────────────


@staff_member_required
def api_views_over_time(request):
    qs = _base_qs(request)
    rows = (
        qs.annotate(date=TruncDate("timestamp"))
        .values("date")
        .annotate(views=Count("id"), visitors=Count("session_hash", distinct=True))
        .order_by("date")
    )
    data = [
        {"date": r["date"].isoformat(), "views": r["views"], "visitors": r["visitors"]}
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_top_pages(request):
    qs = _base_qs(request)
    rows = (
        qs.values("path", "view_name")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    return JsonResponse({"data": list(rows)})


@staff_member_required
def api_top_articles(request):
    qs = _base_qs(request).filter(article__isnull=False)
    rows = (
        qs.values("article__id", "article__title")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    data = [
        {"id": r["article__id"], "title": r["article__title"], "views": r["views"]}
        for r in rows
    ]
    return JsonResponse({"data": data})


@staff_member_required
def api_top_referrers(request):
    qs = _base_qs(request).exclude(Q(referrer_domain="") | Q(referrer_domain__isnull=True))
    rows = (
        qs.values("referrer_domain")
        .annotate(views=Count("id"))
        .order_by("-views")[:15]
    )
    return JsonResponse({"data": list(rows)})


@staff_member_required
def api_geo(request):
    qs = _base_qs(request).exclude(country="")
    rows = (
        qs.values("country", "country_name")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    return JsonResponse({"data": list(rows)})


@staff_member_required
def api_devices(request):
    qs = _base_qs(request)
    devices = list(
        qs.values("device_type").annotate(count=Count("id")).order_by("-count")
    )
    browsers = list(
        qs.exclude(browser="")
        .values("browser")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    oses = list(
        qs.exclude(os="")
        .values("os")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    return JsonResponse({"devices": devices, "browsers": browsers, "oses": oses})


@staff_member_required
def api_categories(request):
    qs = _base_qs(request).filter(category__isnull=False)
    rows = (
        qs.values("category__name")
        .annotate(views=Count("id"))
        .order_by("-views")[:20]
    )
    data = [{"name": r["category__name"], "views": r["views"]} for r in rows]
    return JsonResponse({"data": data})
