from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, StackedInline, TabularInline

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


class ArticlePipelineInline(StackedInline):
    model = ArticlePipeline
    extra = 0
    max_num = 1
    readonly_fields = ("rss_images_at", "content_extracted_at", "og_images_at", "embedded_at", "completed_at")


class ArticleImageInline(TabularInline):
    model = ArticleImage
    extra = 0
    readonly_fields = ("inline_preview", "source_url", "width", "height", "file_size", "is_primary")
    fields = ("inline_preview", "source_url", "is_primary", "width", "height", "file_size")

    @admin.display(description="Preview")
    def inline_preview(self, obj):
        return _img_thumbnail(obj.image.url if obj.image else None, w=80, h=50)


class PipelineStageFilter(admin.SimpleListFilter):
    title = "pipeline stage"
    parameter_name = "pipeline_stage"

    def lookups(self, request, model_admin):
        return [
            ("no_pipeline", "No pipeline"),
            ("new", "New (nothing done)"),
            ("rss_images", "RSS images done"),
            ("content", "Content extracted"),
            ("og_images", "OG images done"),
            ("embedded", "Embedded"),
            ("completed", "Completed"),
        ]

    def queryset(self, request, queryset):
        val = self.value()
        if val == "no_pipeline":
            return queryset.filter(pipeline__isnull=True)
        if val == "new":
            return queryset.filter(
                pipeline__isnull=False,
                pipeline__content_extracted_at__isnull=True,
                pipeline__rss_images_at__isnull=True,
            )
        if val == "rss_images":
            return queryset.filter(
                pipeline__rss_images_at__isnull=False,
                pipeline__content_extracted_at__isnull=True,
            )
        if val == "content":
            return queryset.filter(
                pipeline__content_extracted_at__isnull=False,
                pipeline__embedded_at__isnull=True,
            )
        if val == "og_images":
            return queryset.filter(
                pipeline__og_images_at__isnull=False,
                pipeline__embedded_at__isnull=True,
            )
        if val == "embedded":
            return queryset.filter(
                pipeline__embedded_at__isnull=False,
                pipeline__completed_at__isnull=True,
            )
        if val == "completed":
            return queryset.filter(pipeline__completed_at__isnull=False)
        return queryset


@admin.register(Article)
class ArticleAdmin(ModelAdmin):
    list_display = ("id", "rss_image", "og_image", "title", "feed", "pipeline_status", "published")
    list_display_links = ("id", "title")
    list_filter = ("feed__category", PipelineStageFilter)
    search_fields = ("title", "content")
    raw_id_fields = ("feed",)
    inlines = [ArticlePipelineInline, ArticleImageInline]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("pipeline")
            .prefetch_related("images", "images__source")
        )

    @admin.display(description="Pipeline")
    def pipeline_status(self, obj):
        pipeline = getattr(obj, "pipeline", None)
        if not pipeline:
            return format_html('<span style="color:#9ca3af;">—</span>')

        stages = [
            (pipeline.rss_images_at, "RSS img"),
            (pipeline.content_extracted_at, "Content"),
            (pipeline.og_images_at, "OG img"),
            (pipeline.embedded_at, "Embed"),
            (pipeline.completed_at, "Done"),
        ]

        blocks = []
        for ts, name in stages:
            color = "#22c55e" if ts else "#ef4444"
            title = f"{name}: {ts:%d.%m %H:%M}" if ts else f"{name}: pending"
            blocks.append(format_html(
                '<span title="{}" style="display:inline-block;width:10px;height:10px;'
                'border-radius:2px;background:{}"></span>',
                title, color,
            ))

        return mark_safe(
            '<span style="display:inline-flex;gap:2px;">'
            + "".join(str(b) for b in blocks)
            + '</span>'
        )

    def _find_image(self, obj, slug):
        for i in obj.images.all():
            if i.image and i.source and i.source.slug == slug:
                return i
        return None

    @admin.display(description="RSS")
    def rss_image(self, obj):
        img = self._find_image(obj, "rss-image")
        if not img:
            return ""
        return format_html(
            '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:3px;" />',
            img.image.url,
        )

    @admin.display(description="OG")
    def og_image(self, obj):
        img = self._find_image(obj, "og-image")
        if not img:
            return ""
        return format_html(
            '<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:3px;" />',
            img.image.url,
        )


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
