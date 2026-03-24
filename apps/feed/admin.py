from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline

from .models import Article, ArticleChunk, ArticleImage, Category, Feed


def _img_thumbnail(url, w=60, h=40):
    if not url:
        return ""
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;border-radius:3px;" />',
        url, w, h,
    )


def _img_detail(url):
    if not url:
        return "No image"
    return format_html(
        '<img src="{}" style="max-width:400px;max-height:250px;border-radius:4px;" />',
        url,
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


class ArticleImageInline(TabularInline):
    model = ArticleImage
    extra = 0
    readonly_fields = ("inline_preview", "source_url", "width", "height", "file_size", "is_primary")
    fields = ("inline_preview", "source_url", "is_primary", "width", "height", "file_size")

    @admin.display(description="Preview")
    def inline_preview(self, obj):
        return _img_thumbnail(obj.image.url if obj.image else None, w=80, h=50)


@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("id", "image_preview", "title", "feed", "published", "read", "starred", "embedded")
    list_display_links = ("id", "image_preview", "title")
    list_filter = ("feed__category", "read", "starred", "embedded")
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)
    inlines = [ArticleImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("images")

    @admin.display(description="")
    def image_preview(self, obj):
        imgs = [i for i in obj.images.all() if i.image]
        if not imgs:
            return ""
        parts = [
            format_html(
                '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:3px;{}" />',
                i.image.url,
                "border:2px solid var(--primary-color,#1e88e5);" if i.is_primary else "opacity:0.6;",
            )
            for i in imgs
        ]
        return mark_safe(" ".join(parts))


@admin.register(ArticleChunk)
class ArticleChunkAdmin(ModelAdmin):
    list_display = ("id", "article", "chunk_index", "model", "created_at")
    list_display_links = ("id",)
    list_filter = ("model",)
    raw_id_fields = ("article",)


@admin.register(ArticleImage)
class ArticleImageAdmin(ModelAdmin):
    list_display = ("id", "image_preview", "article", "is_primary", "downloaded", "width", "height", "file_size_display", "created_at")
    list_display_links = ("id", "image_preview")
    list_filter = ("is_primary", "downloaded")
    raw_id_fields = ("article",)
    readonly_fields = ("image_tag", "source_url", "width", "height", "file_size")

    @admin.display(description="")
    def image_preview(self, obj):
        return _img_thumbnail(obj.image.url if obj.image else None, w=120, h=80)

    @admin.display(description="Image")
    def image_tag(self, obj):
        return _img_detail(obj.image.url if obj.image else None)

    @admin.display(description="Size")
    def file_size_display(self, obj):
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        if obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        return f"{obj.file_size / (1024 * 1024):.1f} MB"
