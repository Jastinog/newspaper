from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    APIUsage, Article, ArticleChunk, Category, DeepDive, DeepDiveSource,
    Digest, DigestItem, DigestSection, Feed, TopicEmbedding,
)


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("name", "slug", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Feed)
class FeedAdmin(ModelAdmin):
    list_display = ("title", "category", "enabled", "last_fetched")
    list_filter = ("category", "enabled")
    search_fields = ("title", "url")
    list_editable = ("enabled",)


@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("title", "feed", "published", "read", "starred", "embedded")
    list_filter = ("feed__category", "read", "starred", "embedded")
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)


@admin.register(ArticleChunk)
class ArticleChunkAdmin(ModelAdmin):
    list_display = ("article", "chunk_index", "model", "created_at")
    list_filter = ("model",)
    raw_id_fields = ("article",)


class DigestItemInline(TabularInline):
    model = DigestItem
    extra = 0
    readonly_fields = ("topic", "summary", "order")


class DigestSectionInline(TabularInline):
    model = DigestSection
    extra = 0
    show_change_link = True


@admin.register(DigestSection)
class DigestSectionAdmin(ModelAdmin):
    list_display = ("title", "digest", "order", "item_count")
    raw_id_fields = ("digest",)
    inlines = [DigestItemInline]

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(Digest)
class DigestAdmin(ModelAdmin):
    list_display = ("date", "language", "headline_short", "created_at")
    list_filter = ("language",)
    inlines = [DigestSectionInline]

    @admin.display(description="Headline")
    def headline_short(self, obj):
        return obj.headline[:100] if obj.headline else ""


class DeepDiveSourceInline(TabularInline):
    model = DeepDiveSource
    extra = 0
    raw_id_fields = ("article",)
    readonly_fields = ("relevance",)


@admin.register(DeepDive)
class DeepDiveAdmin(ModelAdmin):
    list_display = ("title_short", "item", "chunks_used", "generation_time_ms", "created_at")
    raw_id_fields = ("item",)
    inlines = [DeepDiveSourceInline]

    @admin.display(description="Title")
    def title_short(self, obj):
        return obj.title[:80] if obj.title else ""


@admin.register(TopicEmbedding)
class TopicEmbeddingAdmin(ModelAdmin):
    list_display = ("topic_index", "description_short", "created_at")
    list_filter = ("topic_index",)

    @admin.display(description="Description")
    def description_short(self, obj):
        return obj.description[:80] if obj.description else ""


@admin.register(APIUsage)
class APIUsageAdmin(ModelAdmin):
    list_display = ("created_at", "service", "api_type", "model", "total_tokens", "cost_usd")
    list_filter = ("service", "api_type", "model")
    date_hierarchy = "created_at"
    raw_id_fields = ("digest", "deep_dive")
