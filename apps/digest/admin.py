from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.core.services.ai import EmbeddingClient

from .models import (
    ArticleUse, Digest, DigestConfig, DigestItem, DigestItemTranslation,
    DigestSection, DigestSectionTranslation, DigestTranslation,
    ItemPipeline, SectionEmbedding,
)


def _img_thumbnail(url, w=60, h=40):
    if not url:
        return ""
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;border-radius:3px;" />',
        url, w, h,
    )


# ── DigestConfig (singleton) ────────────────────────────────────


@admin.register(DigestConfig)
class DigestConfigAdmin(ModelAdmin):
    list_display = ("__str__",)

    fieldsets = (
        ("LLM Model", {
            "classes": ["tab"],
            "description": "OpenAI model and generation parameters",
            "fields": (
                "chat_model",
                "temperature",
                ("max_tokens_analysis", "max_tokens_generation"),
                ("max_tokens_headline", "max_tokens_translation"),
            ),
        }),
        ("Collection", {
            "classes": ["tab"],
            "description": "How articles are found via embedding similarity search",
            "fields": (
                ("hours_lookback", "articles_per_section"),
                ("similarity_threshold", "chunks_per_query"),
                "article_snippet_length",
            ),
        }),
        ("Refinement", {
            "classes": ["tab"],
            "description": "How articles are enriched after story identification",
            "fields": (
                ("context_trim_length", "refine_search_top_k"),
            ),
        }),
        ("Generation", {
            "classes": ["tab"],
            "description": "How many stories the analyzer should identify per section",
            "fields": (
                ("items_per_section_min", "items_per_section_max"),
                "max_workers",
            ),
        }),
        ("Prompts", {
            "classes": ["tab"],
            "description": "System prompts sent to the LLM at each pipeline step",
            "fields": (
                "system_prompt_analysis",
                "system_prompt_generation",
                "system_prompt_headline",
                "system_prompt_translation",
            ),
        }),
    )

    def has_add_permission(self, request):
        return not DigestConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# ── DigestSection ────────────────────────────────────────────────


class DigestSectionTranslationInline(TabularInline):
    model = DigestSectionTranslation
    extra = 1


class SectionEmbeddingInline(TabularInline):
    model = SectionEmbedding
    extra = 1
    fields = ("description", "has_embedding")
    readonly_fields = ("has_embedding",)

    @admin.display(description="Embedding", boolean=True)
    def has_embedding(self, obj):
        return obj.embedding is not None


@admin.action(description="Generate embeddings for selected sections")
def generate_embeddings(modeladmin, request, queryset):
    client = EmbeddingClient()
    total = 0
    for section in queryset:
        pending = list(section.embeddings.filter(embedding__isnull=True))
        if not pending:
            continue
        descriptions = [e.description for e in pending]
        vectors, _ = client.embed_batch(descriptions)
        for emb_obj, vector in zip(pending, vectors):
            emb_obj.embedding = vector
            emb_obj.save(update_fields=["embedding"])
        total += len(pending)
    modeladmin.message_user(request, f"Generated {total} embeddings.")


@admin.register(DigestSection)
class DigestSectionAdmin(ModelAdmin):
    list_display = ("id", "slug", "section_name", "order", "enabled", "embedding_count")
    list_display_links = ("id", "slug")
    list_editable = ("order", "enabled")
    prepopulated_fields = {"slug": []}
    inlines = [DigestSectionTranslationInline, SectionEmbeddingInline]
    actions = [generate_embeddings]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("embeddings", "translations")

    @admin.display(description="Name")
    def section_name(self, obj):
        t = obj.translations.filter(language__is_default=True).first()
        return t.name if t else obj.slug

    @admin.display(description="Embeddings")
    def embedding_count(self, obj):
        embeddings = obj.embeddings.all()
        total = len(embeddings)
        ready = sum(1 for e in embeddings if e.embedding is not None)
        if total == ready:
            return str(total)
        return f"{ready}/{total}"


# ── Digest ───────────────────────────────────────────────────────


class DigestTranslationInline(TabularInline):
    model = DigestTranslation
    extra = 0


class DigestItemInlineShort(TabularInline):
    model = DigestItem
    extra = 0
    fields = ("section", "importance", "order", "item_image_preview")
    readonly_fields = ("item_image_preview",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("image", "section")

    @admin.display(description="Image")
    def item_image_preview(self, obj):
        return _img_thumbnail(obj.best_image_url, w=80, h=50)


@admin.register(Digest)
class DigestAdmin(ModelAdmin):
    list_display = ("id", "date", "stage", "item_count", "created_at")
    list_display_links = ("id", "date")
    inlines = [DigestTranslationInline, DigestItemInlineShort]

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.items.count()


# ── DigestItem ───────────────────────────────────────────────────


class DigestItemTranslationInline(TabularInline):
    model = DigestItemTranslation
    extra = 0
    readonly_fields = ("language", "topic", "summary")


@admin.register(DigestItem)
class DigestItemAdmin(ModelAdmin):
    list_display = ("id", "item_topic", "section", "importance", "digest")
    list_display_links = ("id", "item_topic")
    list_filter = ("section", "digest__date")
    raw_id_fields = ("digest", "image")
    inlines = [DigestItemTranslationInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("section", "digest").prefetch_related("translations")

    @admin.display(description="Topic")
    def item_topic(self, obj):
        t = obj.translations.filter(language__is_default=True).first()
        return t.topic[:80] if t else f"Item #{obj.pk}"


# ── ItemPipeline (debug) ───────────────────────────────────────


@admin.register(ItemPipeline)
class ItemPipelineAdmin(ModelAdmin):
    list_display = ("id", "story_label", "analyzed_at", "refined_at", "generated_at", "translated_at")
    list_display_links = ("id", "story_label")
    list_filter = ("item__digest__date",)
    readonly_fields = (
        "item", "story_label", "article_ids", "search_queries",
        "refined_articles", "analyzed_at", "refined_at", "generated_at", "translated_at",
    )


# ── ArticleUse ─────────────────────────────────────────────────


@admin.register(ArticleUse)
class ArticleUseAdmin(ModelAdmin):
    list_display = ("id", "article", "item", "created_at")
    list_display_links = ("id",)
    list_filter = ("item__digest__date",)
    raw_id_fields = ("article", "item")
