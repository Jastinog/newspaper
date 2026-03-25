from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline

from unfold.admin import StackedInline as UnfoldStackedInline

from .models import Article, ArticleChunk, ArticleImage, ArticleImageSource, ArticlePipeline, Category, Feed


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


class ArticlePipelineInline(UnfoldStackedInline):
    model = ArticlePipeline
    extra = 0
    max_num = 1
    readonly_fields = ("content_extracted_at", "images_fetched_at", "embedded_at")


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
    list_display = ("id", "image_preview", "title", "feed", "published")
    list_display_links = ("id", "image_preview", "title")
    list_filter = ("feed__category",)
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)
    inlines = [ArticlePipelineInline, ArticleImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("images", "images__source")

    @admin.display(description="")
    def image_preview(self, obj):
        imgs = [i for i in obj.images.all() if i.image]
        if not imgs:
            return ""
        parts = []
        for i in imgs:
            slug = i.source.slug if i.source else ""
            if slug == "og-image":
                border = "border:2px solid #1e88e5;"
                label = "OG"
            elif slug == "rss-image":
                border = "border:2px solid #43a047;"
                label = "RSS"
            else:
                border = "opacity:0.6;"
                label = ""
            img_html = format_html(
                '<span style="display:inline-block;position:relative;margin-right:2px;">'
                '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:3px;{}" />'
                '<span style="position:absolute;bottom:0;right:0;font-size:8px;background:rgba(0,0,0,.6);color:#fff;padding:0 2px;border-radius:2px;">{}</span>'
                '</span>',
                i.image.url, border, label,
            )
            parts.append(img_html)
        return mark_safe("".join(parts))


@admin.register(ArticleImageSource)
class ArticleImageSourceAdmin(ModelAdmin):
    list_display = ("id", "slug", "name")
    list_display_links = ("id", "slug")


@admin.register(ArticleChunk)
class ArticleChunkAdmin(ModelAdmin):
    list_display = ("id", "article", "chunk_index", "model", "created_at")
    list_display_links = ("id",)
    list_filter = ("model",)
    raw_id_fields = ("article",)


@admin.register(ArticleImage)
class ArticleImageAdmin(ModelAdmin):
    list_display = ("id", "image_preview", "article", "source", "is_primary", "downloaded", "width", "height", "file_size_display", "created_at")
    list_display_links = ("id", "image_preview")
    list_filter = ("source", "is_primary", "downloaded")
    raw_id_fields = ("article",)
    readonly_fields = ("image_tag", "source_url", "width", "height", "file_size")
    list_select_related = ("source",)

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
