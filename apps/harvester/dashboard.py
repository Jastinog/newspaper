import json
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.feed.models import Article, ArticlePipeline, Feed
from apps.harvester.models import (
    HarvesterContent,
    HarvesterEmbedding,
    HarvesterFeed,
    HarvesterImage,
)


def _build_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def _daily_series(day_map, dates, field, default=0):
    return [day_map.get(str(d), {}).get(field, default) for d in dates]


def build_harvester_context(request):
    now = timezone.now()
    today = now.date()
    twenty_four_hours_ago = now - timedelta(hours=24)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    dates = _build_labels(now, 30)
    labels = [d.strftime("%d.%m") for d in dates]

    # ── KPI cards ────────────────────────────────────────────
    articles_today = (
        HarvesterFeed.objects
        .filter(started_at__date=today)
        .aggregate(n=Sum("new_articles"))["n"] or 0
    )

    pending_extraction = ArticlePipeline.objects.filter(
        content_extracted_at__isnull=True,
    ).count()

    pending_embedding = (
        ArticlePipeline.objects
        .filter(content_extracted_at__isnull=False, embedded_at__isnull=True)
        .exclude(article__content="")
        .count()
    )

    completed_total = ArticlePipeline.objects.filter(
        completed_at__isnull=False,
    ).count()

    # Error rate (24h) across all harvester tables
    error_filter = Q(status="error", started_at__gte=twenty_four_hours_ago)
    total_filter = Q(started_at__gte=twenty_four_hours_ago)
    errors_24h = sum([
        HarvesterFeed.objects.filter(error_filter).count(),
        HarvesterContent.objects.filter(error_filter).count(),
        HarvesterImage.objects.filter(error_filter).count(),
        HarvesterEmbedding.objects.filter(error_filter).count(),
    ])
    total_24h = sum([
        HarvesterFeed.objects.filter(total_filter).count(),
        HarvesterContent.objects.filter(total_filter).count(),
        HarvesterImage.objects.filter(total_filter).count(),
        HarvesterEmbedding.objects.filter(total_filter).count(),
    ])
    error_rate_24h = (
        f"{errors_24h / total_24h * 100:.1f}%" if total_24h > 0 else "—"
    )

    # Active feeds (24h)
    feeds_active_24h = (
        HarvesterFeed.objects
        .filter(started_at__gte=twenty_four_hours_ago)
        .values("feed")
        .distinct()
        .count()
    )
    feeds_enabled = Feed.objects.filter(enabled=True).count()

    # ── Chart 1: New articles per day ────────────────────────
    new_articles_daily = (
        HarvesterFeed.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(total=Sum("new_articles"))
        .order_by("day")
    )
    new_articles_map = {str(r["day"]): {"total": r["total"]} for r in new_articles_daily}

    new_articles_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "New Articles",
            "data": _daily_series(new_articles_map, dates, "total"),
            "backgroundColor": "rgba(34, 197, 94, 0.5)",
            "borderColor": "rgb(34, 197, 94)",
            "borderWidth": 2,
            "type": "bar",
        }],
    })

    # ── Chart 2: Feed fetches success vs error ───────────────
    feed_fetches_daily = (
        HarvesterFeed.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(
            total=Count("id"),
            errors=Count("id", filter=Q(status="error")),
        )
        .order_by("day")
    )
    feed_fetches_map = {
        str(r["day"]): {
            "success": r["total"] - r["errors"],
            "errors": r["errors"],
        }
        for r in feed_fetches_daily
    }

    feed_fetches_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Success",
                "data": _daily_series(feed_fetches_map, dates, "success"),
                "backgroundColor": "rgba(34, 197, 94, 0.5)",
                "borderColor": "rgb(34, 197, 94)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "fetches",
            },
            {
                "label": "Error",
                "data": _daily_series(feed_fetches_map, dates, "errors"),
                "backgroundColor": "rgba(239, 68, 68, 0.5)",
                "borderColor": "rgb(239, 68, 68)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "fetches",
            },
        ],
    })

    # ── Chart 3: Content extraction ──────────────────────────
    extraction_daily = (
        HarvesterContent.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(
            extracted=Sum("articles_extracted"),
            failed=Sum("articles_failed"),
            fallback=Sum("articles_fallback"),
        )
        .order_by("day")
    )
    extraction_map = {
        str(r["day"]): {
            "extracted": r["extracted"] or 0,
            "failed": r["failed"] or 0,
            "fallback": r["fallback"] or 0,
        }
        for r in extraction_daily
    }

    extraction_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Extracted",
                "data": _daily_series(extraction_map, dates, "extracted"),
                "backgroundColor": "rgba(34, 197, 94, 0.5)",
                "borderColor": "rgb(34, 197, 94)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "extraction",
            },
            {
                "label": "Fallback",
                "data": _daily_series(extraction_map, dates, "fallback"),
                "backgroundColor": "rgba(234, 179, 8, 0.5)",
                "borderColor": "rgb(234, 179, 8)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "extraction",
            },
            {
                "label": "Failed",
                "data": _daily_series(extraction_map, dates, "failed"),
                "backgroundColor": "rgba(239, 68, 68, 0.5)",
                "borderColor": "rgb(239, 68, 68)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "extraction",
            },
        ],
    })

    # ── Chart 4: Image downloads ─────────────────────────────
    images_daily = (
        HarvesterImage.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(
            downloaded=Sum("images_downloaded"),
            skipped=Sum("images_skipped"),
        )
        .order_by("day")
    )
    images_map = {
        str(r["day"]): {
            "downloaded": r["downloaded"] or 0,
            "skipped": r["skipped"] or 0,
        }
        for r in images_daily
    }

    images_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Downloaded",
                "data": _daily_series(images_map, dates, "downloaded"),
                "backgroundColor": "rgba(99, 102, 241, 0.5)",
                "borderColor": "rgb(99, 102, 241)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "images",
            },
            {
                "label": "Skipped",
                "data": _daily_series(images_map, dates, "skipped"),
                "backgroundColor": "rgba(156, 163, 175, 0.5)",
                "borderColor": "rgb(156, 163, 175)",
                "borderWidth": 1,
                "type": "bar",
                "stack": "images",
            },
        ],
    })

    # ── Chart 5: Embeddings ──────────────────────────────────
    embeddings_daily = (
        HarvesterEmbedding.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(
            embedded=Sum("articles_embedded"),
            chunks=Sum("chunks_created"),
        )
        .order_by("day")
    )
    embeddings_map = {
        str(r["day"]): {
            "embedded": r["embedded"] or 0,
            "chunks": r["chunks"] or 0,
        }
        for r in embeddings_daily
    }

    embeddings_chart = json.dumps({
        "labels": labels,
        "datasets": [
            {
                "label": "Articles Embedded",
                "data": _daily_series(embeddings_map, dates, "embedded"),
                "borderColor": "rgb(99, 102, 241)",
                "backgroundColor": "rgba(99, 102, 241, 0.1)",
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            },
            {
                "label": "Chunks Created",
                "data": _daily_series(embeddings_map, dates, "chunks"),
                "borderColor": "rgb(168, 85, 247)",
                "backgroundColor": "rgba(168, 85, 247, 0.1)",
                "borderWidth": 2,
                "fill": True,
                "tension": 0.3,
            },
        ],
    })

    # ── Chart 6: Embedding tokens ────────────────────────────
    tokens_daily = (
        HarvesterEmbedding.objects
        .filter(started_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(started_at)"})
        .values("day")
        .annotate(tokens=Sum("tokens_used"))
        .order_by("day")
    )
    tokens_map = {str(r["day"]): {"tokens": r["tokens"] or 0} for r in tokens_daily}

    tokens_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Tokens Used",
            "data": _daily_series(tokens_map, dates, "tokens"),
            "borderColor": "rgb(234, 179, 8)",
            "backgroundColor": "rgba(234, 179, 8, 0.1)",
            "borderWidth": 2,
            "fill": True,
            "tension": 0.3,
        }],
    })

    # ── Chart 7: Pipeline completion rate ────────────────────
    completion_daily = (
        ArticlePipeline.objects
        .filter(completed_at__gte=thirty_days_ago)
        .extra(select={"day": "DATE(completed_at)"})
        .values("day")
        .annotate(completed=Count("id"))
        .order_by("day")
    )
    completion_map = {str(r["day"]): {"completed": r["completed"]} for r in completion_daily}

    completion_chart = json.dumps({
        "labels": labels,
        "datasets": [{
            "label": "Completed",
            "data": _daily_series(completion_map, dates, "completed"),
            "borderColor": "rgb(34, 197, 94)",
            "backgroundColor": "rgba(34, 197, 94, 0.1)",
            "borderWidth": 2,
            "fill": True,
            "tension": 0.3,
        }],
    })

    # ── Table: Problem feeds (last 7 days) ───────────────────
    problem_feeds_qs = (
        HarvesterFeed.objects
        .filter(started_at__gte=seven_days_ago)
        .values("feed", "feed__title")
        .annotate(
            total=Count("id"),
            errors=Count("id", filter=Q(status="error")),
        )
        .filter(total__gte=3, errors__gt=0)
        .order_by("-errors")[:10]
    )
    problem_feeds = [
        {
            "title": r["feed__title"][:60],
            "total": r["total"],
            "errors": r["errors"],
            "rate": f"{r['errors'] / r['total'] * 100:.0f}%",
        }
        for r in problem_feeds_qs
    ]

    # ── Table: Recent errors ─────────────────────────────────
    recent_errors = []
    for Model, stage in [
        (HarvesterFeed, "Feed Fetch"),
        (HarvesterContent, "Extraction"),
        (HarvesterImage, "Image DL"),
        (HarvesterEmbedding, "Embedding"),
    ]:
        qs = (
            Model.objects
            .filter(status="error")
            .order_by("-started_at")[:5]
        )
        for run in qs:
            recent_errors.append({
                "stage": stage,
                "date": run.started_at.strftime("%d.%m %H:%M"),
                "error": (run.error_message[:120] + "...") if len(run.error_message) > 120 else run.error_message,
                "started_at": run.started_at,
            })

    recent_errors.sort(key=lambda x: x["started_at"], reverse=True)
    recent_errors = recent_errors[:15]
    for e in recent_errors:
        del e["started_at"]

    # ── Total articles in DB ─────────────────────────────────
    total_articles = Article.objects.count()

    return {
        # KPI
        "articles_today": f"{articles_today:,}",
        "pending_extraction": f"{pending_extraction:,}",
        "pending_embedding": f"{pending_embedding:,}",
        "completed_total": f"{completed_total:,}",
        "error_rate_24h": error_rate_24h,
        "errors_24h": errors_24h,
        "total_runs_24h": total_24h,
        "feeds_active_24h": feeds_active_24h,
        "feeds_enabled": feeds_enabled,
        "total_articles": f"{total_articles:,}",
        # Charts
        "new_articles_chart": new_articles_chart,
        "feed_fetches_chart": feed_fetches_chart,
        "extraction_chart": extraction_chart,
        "images_chart": images_chart,
        "embeddings_chart": embeddings_chart,
        "tokens_chart": tokens_chart,
        "completion_chart": completion_chart,
        # Tables
        "problem_feeds": problem_feeds,
        "recent_errors": recent_errors,
    }
