from django.contrib import admin

from .models import Article, ArticleChunk, Category, Digest, DigestSection, Feed


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "enabled", "last_fetched")
    list_filter = ("category", "enabled")
    search_fields = ("title", "url")
    list_editable = ("enabled",)


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "feed", "published", "read", "starred", "embedded")
    list_filter = ("feed__category", "read", "starred", "embedded")
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)


@admin.register(ArticleChunk)
class ArticleChunkAdmin(admin.ModelAdmin):
    list_display = ("article", "chunk_index", "model", "created_at")
    list_filter = ("model",)
    raw_id_fields = ("article",)


class DigestSectionInline(admin.TabularInline):
    model = DigestSection
    extra = 0


@admin.register(Digest)
class DigestAdmin(admin.ModelAdmin):
    list_display = ("date", "headline_short", "created_at")
    inlines = [DigestSectionInline]

    @admin.display(description="Headline")
    def headline_short(self, obj):
        return obj.headline[:100] if obj.headline else ""
