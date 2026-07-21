from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    DigestConfig, DigestSection, DigestSectionTranslation, SectionEmbedding,
)


# ── DigestConfig (singleton) ────────────────────────────────────


@admin.register(DigestConfig)
class DigestConfigAdmin(ModelAdmin):
    list_display = ("__str__",)

    fieldsets = (
        ("Embedding sections", {
            "classes": ["tab"],
            "description": "Settings for section assignment (embedding match).",
            "fields": (
                "embed_score_floor",
                ("hours_lookback", "edition_items_per_section"),
            ),
        }),
        ("LLM Model (legacy)", {
            "classes": ["tab"],
            "description": "Unused — kept for the legacy OpenAI pipeline config",
            "fields": (
                ("chat_model", "planner_model"),
                ("temperature", "max_tokens_generation"),
            ),
        }),
        ("Edition (legacy LLM)", {
            "classes": ["tab"],
            "description": "Unused — kept for the legacy OpenAI pipeline config",
            "fields": (
                "edition_max_workers",
                ("edition_article_card_tokens", "edition_article_body_tokens"),
                ("edition_max_articles_per_story", "edition_writer_budget_tokens"),
                "edition_planner_budget_tokens",
            ),
        }),
        ("Prompts", {
            "classes": ["tab"],
            "fields": (
                "system_prompt_planner",
                "system_prompt_writer",
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


@admin.register(DigestSection)
class DigestSectionAdmin(ModelAdmin):
    list_display = ("id", "slug", "section_name", "seed_count", "order", "enabled")
    list_display_links = ("id", "slug")
    list_editable = ("order", "enabled")
    prepopulated_fields = {"slug": []}
    inlines = [DigestSectionTranslationInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("translations")

    @admin.display(description="Name")
    def section_name(self, obj):
        t = obj.translations.filter(language__is_default=True).first()
        return t.name if t else obj.slug

    @admin.display(description="Seeds")
    def seed_count(self, obj):
        return obj.embeddings.count()


@admin.register(SectionEmbedding)
class SectionEmbeddingAdmin(ModelAdmin):
    """Seed phrases and their vectors — managed by `initdigest`, read-only here."""

    list_display = ("id", "section", "text")
    list_display_links = ("id", "text")
    list_filter = ("section",)
    search_fields = ("text",)
    readonly_fields = ("section", "text", "embedding")

    def has_add_permission(self, request):
        return False
