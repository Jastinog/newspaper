from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    HarvesterContent,
    HarvesterEmbedding,
    HarvesterFeed,
    HarvesterImage,
    RunStatus,
)


def _status_display(obj):
    if obj.status == RunStatus.SUCCESS:
        return format_html('<span style="color:#2d6a4f;font-weight:600">{}</span>', "OK")
    return format_html(
        '<span style="color:#c1121f;font-weight:600" title="{}">ERR</span>',
        obj.error_message or "Unknown error",
    )


def _duration_display(obj):
    d = obj.duration
    if d:
        return f"{d.total_seconds():.1f}s"
    return "\u2014"


# --- Feed Fetch ---

class FeedFetchArticleInline(TabularInline):
    model = HarvesterFeed.articles.through
    extra = 0
    raw_id_fields = ["article"]
    verbose_name = "article"
    verbose_name_plural = "articles"


@admin.register(HarvesterFeed)
class HarvesterFeedAdmin(ModelAdmin):
    list_display = ["feed", "status_display", "new_articles", "duration_display", "started_at"]
    list_display_links = ["feed"]
    list_filter = ["status", "feed__category"]
    search_fields = ["feed__title"]
    raw_id_fields = ["feed"]
    date_hierarchy = "started_at"
    list_per_page = 50
    inlines = [FeedFetchArticleInline]
    exclude = ["articles"]

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return _status_display(obj)

    @admin.display(description="Duration")
    def duration_display(self, obj):
        return _duration_display(obj)


# --- Content Extract ---

class ExtractArticleInline(TabularInline):
    model = HarvesterContent.articles.through
    extra = 0
    raw_id_fields = ["article"]
    verbose_name = "article"
    verbose_name_plural = "articles"


@admin.register(HarvesterContent)
class HarvesterContentAdmin(ModelAdmin):
    list_display = [
        "started_at", "status_display",
        "articles_found", "articles_extracted", "articles_failed", "articles_fallback",
        "duration_display",
    ]
    list_filter = ["status"]
    date_hierarchy = "started_at"
    list_per_page = 50
    inlines = [ExtractArticleInline]
    exclude = ["articles"]

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return _status_display(obj)

    @admin.display(description="Duration")
    def duration_display(self, obj):
        return _duration_display(obj)


# --- Image Download ---

@admin.register(HarvesterImage)
class HarvesterImageAdmin(ModelAdmin):
    list_display = [
        "started_at", "status_display",
        "images_found", "images_downloaded", "images_skipped",
        "duration_display",
    ]
    list_filter = ["status"]
    date_hierarchy = "started_at"
    list_per_page = 50

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return _status_display(obj)

    @admin.display(description="Duration")
    def duration_display(self, obj):
        return _duration_display(obj)


# --- Embed ---

@admin.register(HarvesterEmbedding)
class HarvesterEmbeddingAdmin(ModelAdmin):
    list_display = [
        "started_at", "status_display",
        "articles_found", "articles_embedded", "chunks_created", "tokens_used",
        "duration_display",
    ]
    list_filter = ["status"]
    date_hierarchy = "started_at"
    list_per_page = 50

    @admin.display(description="Status", ordering="status")
    def status_display(self, obj):
        return _status_display(obj)

    @admin.display(description="Duration")
    def duration_display(self, obj):
        return _duration_display(obj)
