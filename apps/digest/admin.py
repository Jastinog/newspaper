from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.core.services.ai import EmbeddingClient

from .models import Digest, DigestItem, DigestSection, DigestTopic, TopicEmbedding


def _img_thumbnail(url, w=60, h=40):
    if not url:
        return ""
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;border-radius:3px;" />',
        url, w, h,
    )


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
