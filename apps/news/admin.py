from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    APIUsage, Article, ArticleChunk, ArticleImage, Category, DeepDive,
    DeepDiveSource, Digest, DigestItem, DigestSection, DigestTopic, Feed,
    TopicEmbedding,
)


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
    list_display = ("id", "title", "category", "enabled", "last_fetched")
    list_display_links = ("id", "title")
    list_filter = ("category", "enabled")
    search_fields = ("title", "url")
    list_editable = ("enabled",)


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


class DigestItemInline(TabularInline):
    model = DigestItem
    extra = 0
    readonly_fields = ("topic", "summary", "order", "item_image_preview")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("image")

    @admin.display(description="Image")
    def item_image_preview(self, obj):
        return _img_thumbnail(obj.best_image_url, w=80, h=50)


class DigestSectionInline(TabularInline):
    model = DigestSection
    extra = 0
    show_change_link = True


@admin.register(DigestSection)
class DigestSectionAdmin(ModelAdmin):
    list_display = ("id", "title", "digest", "order", "item_count")
    list_display_links = ("id", "title")
    raw_id_fields = ("digest",)
    inlines = [DigestItemInline]

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(Digest)
class DigestAdmin(ModelAdmin):
    list_display = ("id", "date", "language", "headline_short", "created_at")
    list_display_links = ("id", "date")
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
    list_display = ("id", "title_short", "item", "chunks_used", "generation_time_ms", "created_at")
    list_display_links = ("id", "title_short")
    raw_id_fields = ("item",)
    inlines = [DeepDiveSourceInline]

    @admin.display(description="Title")
    def title_short(self, obj):
        return obj.title[:80] if obj.title else ""


class TopicEmbeddingInline(TabularInline):
    model = TopicEmbedding
    extra = 1
    fields = ("description", "has_embedding")
    readonly_fields = ("has_embedding",)

    @admin.display(description="Embedding", boolean=True)
    def has_embedding(self, obj):
        return obj.embedding is not None


@admin.action(description="Generate embeddings for selected topics")
def generate_embeddings(modeladmin, request, queryset):
    from .services.ai import EmbeddingClient
    client = EmbeddingClient()
    total = 0
    for topic in queryset:
        pending = list(topic.embeddings.filter(embedding__isnull=True))
        if not pending:
            continue
        descriptions = [e.description for e in pending]
        vectors, _ = client.embed_batch(descriptions)
        for emb_obj, vector in zip(pending, vectors):
            emb_obj.embedding = vector
            emb_obj.save(update_fields=["embedding"])
        total += len(pending)
    modeladmin.message_user(request, f"Generated {total} embeddings.")


@admin.register(DigestTopic)
class DigestTopicAdmin(ModelAdmin):
    list_display = ("id", "name_en", "order", "enabled", "embedding_count")
    list_display_links = ("id", "name_en")
    list_editable = ("order", "enabled")
    inlines = [TopicEmbeddingInline]
    actions = [generate_embeddings]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("embeddings")

    @admin.display(description="Embeddings")
    def embedding_count(self, obj):
        embeddings = obj.embeddings.all()
        total = len(embeddings)
        ready = sum(1 for e in embeddings if e.embedding is not None)
        if total == ready:
            return str(total)
        return f"{ready}/{total}"


@admin.register(APIUsage)
class APIUsageAdmin(ModelAdmin):
    list_display = ("id", "created_at", "service", "api_type", "model", "total_tokens", "cost_usd")
    list_display_links = ("id",)
    list_filter = ("service", "api_type", "model")
    date_hierarchy = "created_at"
    raw_id_fields = ("digest", "deep_dive")
