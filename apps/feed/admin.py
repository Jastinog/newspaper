from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Article, ArticleChunk, Category, Feed


def _img_thumbnail(url, w=60, h=40):
    if not url:
        return ""
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;border-radius:3px;" />',
        url, w, h,
    )


@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("id", "name", "slug", "order")
    list_display_links = ("id", "name")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Feed)
class FeedAdmin(ModelAdmin):
    list_display = ("id", "title", "category", "country", "language", "reliability", "lean", "factuality", "enabled", "last_fetched")
    list_display_links = ("id", "title")
    list_filter = ("category", "country__region", "country", "language", "enabled", "reliability", "lean", "factuality")
    search_fields = ("title", "url")
    list_editable = ("enabled", "lean", "factuality")


@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("id", "thumb", "title", "feed", "status", "published")
    list_display_links = ("id", "title")
    list_filter = ("status", "feed__category")
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)
    readonly_fields = ("image_preview",)
    fields = (
        "feed", "title", "slug", "url", "published",
        "status", "image_url", "image", "image_preview",
        "content",
    )

    @admin.display(description="")
    def thumb(self, obj):
        return _img_thumbnail(obj.image.url if obj.image else None, w=50, h=35)

    @admin.display(description="Image")
    def image_preview(self, obj):
        if not obj.image:
            return "No image"
        return format_html(
            '<img src="{}" style="max-width:400px;max-height:250px;border-radius:4px;" />',
            obj.image.url,
        )


@admin.register(ArticleChunk)
class ArticleChunkAdmin(ModelAdmin):
    list_display = ("id", "article", "chunk_index", "model", "created_at")
    list_display_links = ("id",)
    list_filter = ("model",)
    raw_id_fields = ("article",)
