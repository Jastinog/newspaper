import json
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMinute
from django.utils import timezone

from apps.feed.models import Article, ArticlePipeline, Feed
from apps.harvester.models import (
    PipelineSettings, PipelineEvent, STAGE_FIELDS,
    HarvesterContent,
    HarvesterEmbedding,
    HarvesterFeed,
    HarvesterImage,
)

# ── Color palette ─────────────────────────────────────────
GREEN = ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.5)")
GREEN_FILL = ("rgb(34, 197, 94)", "rgba(34, 197, 94, 0.1)")
RED = ("rgb(239, 68, 68)", "rgba(239, 68, 68, 0.5)")
INDIGO = ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.5)")
INDIGO_FILL = ("rgb(99, 102, 241)", "rgba(99, 102, 241, 0.1)")
YELLOW = ("rgb(234, 179, 8)", "rgba(234, 179, 8, 0.5)")
YELLOW_FILL = ("rgb(234, 179, 8)", "rgba(234, 179, 8, 0.1)")
GRAY = ("rgb(156, 163, 175)", "rgba(156, 163, 175, 0.5)")
PURPLE_FILL = ("rgb(168, 85, 247)", "rgba(168, 85, 247, 0.1)")


# ── Helpers ───────────────────────────────────────────────
def _build_day_labels(now, days=30):
    return [
        (now - timedelta(days=days - 1 - i)).date()
        for i in range(days)
    ]


def _build_minute_labels(now, minutes=60):
    return [
        (now - timedelta(minutes=minutes - 1 - i)).replace(second=0, microsecond=0)
        for i in range(minutes)
    ]


def _series(data_map, keys, field, default=0):
    return [data_map.get(k, {}).get(field, default) for k in keys]


def _bar_ds(label, data, color, stack=None, border_width=1):
    border, bg = color
    ds = {
        "label": label, "data": data,
        "backgroundColor": bg, "borderColor": border,
        "borderWidth": border_width, "type": "bar",
    }
    if stack:
        ds["stack"] = stack
    return ds


def _line_ds(label, data, color):
    border, bg = color
    return {
        "label": label, "data": data,
        "borderColor": border, "backgroundColor": bg,
        "borderWidth": 2, "fill": True, "tension": 0.3,
    }


def _chart(labels, datasets):
    return json.dumps({"labels": labels, "datasets": datasets})


def _build_timeline_data(now, minutes=5):
    window_start = now - timedelta(minutes=minutes)
    events = list(
        PipelineEvent.objects
        .filter(started_at__gte=window_start)
        .values("stage", "started_at", "finished_at", "duration_ms", "success")
        .order_by("started_at")
    )
    return json.dumps({
        "window_start": window_start.timestamp() * 1000,
        "window_end": now.timestamp() * 1000,
        "events": [
            {
                "stage": e["stage"],
                "start": e["started_at"].timestamp() * 1000,
                "end": e["finished_at"].timestamp() * 1000,
                "duration_ms": e["duration_ms"],
                "ok": e["success"],
            }
            for e in events
        ],
    })


def build_harvester_context(request):
    now = timezone.now()
    today = now.date()
    twenty_four_hours_ago = now - timedelta(hours=24)
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    dates = _build_day_labels(now, 30)
    day_keys = [str(d) for d in dates]
    day_display = [d.strftime("%d.%m") for d in dates]

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

    feeds_active_24h = (
        HarvesterFeed.objects
        .filter(started_at__gte=twenty_four_hours_ago)
        .values("feed")
        .distinct()
        .count()
    )
    feeds_enabled = Feed.objects.filter(enabled=True).count()

    # ── Minute-level data (last 60 min) ──────────────────────
    sixty_minutes_ago = now - timedelta(minutes=60)
    minute_labels = _build_minute_labels(now, 60)
    minute_keys = [m.strftime("%Y-%m-%d %H:%M") for m in minute_labels]
    minute_display = [k[-5:] for k in minute_keys]

    # Single query for HarvesterFeed minute data (articles + fetches)
    feed_min_qs = (
        HarvesterFeed.objects
        .filter(started_at__gte=sixty_minutes_ago)
        .annotate(minute=TruncMinute("started_at"))
        .values("minute")
        .annotate(
            new_articles=Sum("new_articles"),
            total=Count("id"),
            errors=Count("id", filter=Q(status="error")),
        )
        .order_by("minute")
    )
    feed_min_map = {}
    for r in feed_min_qs:
        feed_min_map[r["minute"].strftime("%Y-%m-%d %H:%M")] = {
            "new_articles": r["new_articles"] or 0,
            "success": r["total"] - r["errors"],
            "errors": r["errors"],
        }

    new_articles_min_chart = _chart(minute_display, [
        _bar_ds("New Articles", _series(feed_min_map, minute_keys, "new_articles"), GREEN),
    ])

    feed_fetches_min_chart = _chart(minute_display, [
        _bar_ds("Success", _series(feed_min_map, minute_keys, "success"), GREEN, stack="fetches"),
        _bar_ds("Error", _series(feed_min_map, minute_keys, "errors"), RED, stack="fetches"),
    ])

    # Extraction per minute
    extraction_min_qs = (
        HarvesterContent.objects
        .filter(started_at__gte=sixty_minutes_ago)
        .annotate(minute=TruncMinute("started_at"))
        .values("minute")
        .annotate(
            extracted=Sum("articles_extracted"),
            failed=Sum("articles_failed"),
        )
        .order_by("minute")
    )
    extraction_min_map = {
        r["minute"].strftime("%Y-%m-%d %H:%M"): {
            "extracted": r["extracted"] or 0,
            "failed": r["failed"] or 0,
        }
        for r in extraction_min_qs
    }
    extraction_min_chart = _chart(minute_display, [
        _bar_ds("Extracted", _series(extraction_min_map, minute_keys, "extracted"), GREEN, stack="extraction"),
        _bar_ds("Failed", _series(extraction_min_map, minute_keys, "failed"), RED, stack="extraction"),
    ])

    # Pipeline completions per minute
    completion_min_qs = (
        ArticlePipeline.objects
        .filter(completed_at__gte=sixty_minutes_ago)
        .annotate(minute=TruncMinute("completed_at"))
        .values("minute")
        .annotate(completed=Count("id"))
        .order_by("minute")
    )
    completion_min_map = {
        r["minute"].strftime("%Y-%m-%d %H:%M"): {"completed": r["completed"]}
        for r in completion_min_qs
    }
    completion_min_chart = _chart(minute_display, [
        _line_ds("Completed", _series(completion_min_map, minute_keys, "completed"), GREEN_FILL),
    ])

    # ── Daily data (last 30 days) ────────────────────────────

    # Single query for HarvesterFeed daily data (articles + fetches)
    feed_daily_qs = (
        HarvesterFeed.objects
        .filter(started_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(
            new_articles=Sum("new_articles"),
            total=Count("id"),
            errors=Count("id", filter=Q(status="error")),
        )
        .order_by("day")
    )
    feed_daily_map = {}
    for r in feed_daily_qs:
        feed_daily_map[str(r["day"])] = {
            "new_articles": r["new_articles"] or 0,
            "success": r["total"] - r["errors"],
            "errors": r["errors"],
        }

    new_articles_chart = _chart(day_display, [
        _bar_ds("New Articles", _series(feed_daily_map, day_keys, "new_articles"), GREEN, border_width=2),
    ])

    feed_fetches_chart = _chart(day_display, [
        _bar_ds("Success", _series(feed_daily_map, day_keys, "success"), GREEN, stack="fetches"),
        _bar_ds("Error", _series(feed_daily_map, day_keys, "errors"), RED, stack="fetches"),
    ])

    # Content extraction
    extraction_daily = (
        HarvesterContent.objects
        .filter(started_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("started_at"))
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
    extraction_chart = _chart(day_display, [
        _bar_ds("Extracted", _series(extraction_map, day_keys, "extracted"), GREEN, stack="extraction"),
        _bar_ds("Fallback", _series(extraction_map, day_keys, "fallback"), YELLOW, stack="extraction"),
        _bar_ds("Failed", _series(extraction_map, day_keys, "failed"), RED, stack="extraction"),
    ])

    # Image downloads
    images_daily = (
        HarvesterImage.objects
        .filter(started_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("started_at"))
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
    images_chart = _chart(day_display, [
        _bar_ds("Downloaded", _series(images_map, day_keys, "downloaded"), INDIGO, stack="images"),
        _bar_ds("Skipped", _series(images_map, day_keys, "skipped"), GRAY, stack="images"),
    ])

    # Embeddings
    embeddings_daily = (
        HarvesterEmbedding.objects
        .filter(started_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("started_at"))
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
    embeddings_chart = _chart(day_display, [
        _line_ds("Articles Embedded", _series(embeddings_map, day_keys, "embedded"), INDIGO_FILL),
        _line_ds("Chunks Created", _series(embeddings_map, day_keys, "chunks"), PURPLE_FILL),
    ])

    # Embedding tokens
    tokens_daily = (
        HarvesterEmbedding.objects
        .filter(started_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(tokens=Sum("tokens_used"))
        .order_by("day")
    )
    tokens_map = {str(r["day"]): {"tokens": r["tokens"] or 0} for r in tokens_daily}
    tokens_chart = _chart(day_display, [
        _line_ds("Tokens Used", _series(tokens_map, day_keys, "tokens"), YELLOW_FILL),
    ])

    # Pipeline completion rate
    completion_daily = (
        ArticlePipeline.objects
        .filter(completed_at__gte=thirty_days_ago)
        .annotate(day=TruncDate("completed_at"))
        .values("day")
        .annotate(completed=Count("id"))
        .order_by("day")
    )
    completion_map = {str(r["day"]): {"completed": r["completed"]} for r in completion_daily}
    completion_chart = _chart(day_display, [
        _line_ds("Completed", _series(completion_map, day_keys, "completed"), GREEN_FILL),
    ])

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
        for run in Model.objects.filter(status="error").order_by("-started_at")[:5]:
            recent_errors.append((run.started_at, {
                "stage": stage,
                "date": run.started_at.strftime("%d.%m %H:%M"),
                "error": (run.error_message[:120] + "...") if len(run.error_message) > 120 else run.error_message,
            }))

    recent_errors.sort(key=lambda x: x[0], reverse=True)
    recent_errors = [row for _, row in recent_errors[:15]]

    # ── Total articles in DB ─────────────────────────────────
    total_articles = Article.objects.count()

    # ── Pipeline state ────────────────────────────────────────
    from apps.harvester.services.pipeline import get_manager
    ps = PipelineSettings.load()
    pipeline_running = get_manager() is not None
    pipeline_active = ps.is_active

    return {
        # Pipeline control
        "pipeline_running": pipeline_running,
        "pipeline_active": pipeline_active,
        "stage_toggles": {name: getattr(ps, name) for name, _ in STAGE_FIELDS},
        "stage_labels": STAGE_FIELDS,
        "stage_toggles_on": [name for name, _ in STAGE_FIELDS if getattr(ps, name)],
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
        # Minute charts
        "new_articles_min_chart": new_articles_min_chart,
        "feed_fetches_min_chart": feed_fetches_min_chart,
        "extraction_min_chart": extraction_min_chart,
        "completion_min_chart": completion_min_chart,
        # Daily charts
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
        # Timeline
        "timeline_data": _build_timeline_data(now),
    }
