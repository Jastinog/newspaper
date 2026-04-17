from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Digest, DigestConfig, DigestItem, DigestItemTranslation,
    DigestRun, DigestSection, DigestSectionTranslation, DigestTranslation,
    ItemPipeline,
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
            "fields": (
                ("chat_model", "planner_model"),
                ("temperature", "max_tokens_generation"),
                "hours_lookback",
            ),
        }),
        ("Edition", {
            "classes": ["tab"],
            "description": "Settings for the Edition pipeline (collect -> plan -> write)",
            "fields": (
                ("edition_items_per_section", "edition_max_workers"),
                ("edition_article_card_tokens", "edition_article_body_tokens"),
                ("edition_max_articles_per_story", "edition_writer_budget_tokens"),
                ("edition_planner_budget_tokens", "edition_max_planner_articles"),
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
    list_display = ("id", "slug", "section_name", "order", "enabled")
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


# ── Digest ───────────────────────────────────────────────────────


class DigestRunInline(TabularInline):
    model = DigestRun
    extra = 0
    can_delete = False
    fields = (
        "model", "items_per_section", "started_at", "completed_at",
        "articles_collected", "stories_planned",
        "plan_duration_ms", "plan_input_tokens", "plan_output_tokens", "plan_cost_usd",
        "items_generated", "items_failed",
        "write_duration_ms", "write_input_tokens", "write_output_tokens", "write_cost_usd",
        "total_cost_usd",
    )
    readonly_fields = fields


class DigestTranslationInline(TabularInline):
    model = DigestTranslation
    extra = 0


class DigestItemInlineShort(TabularInline):
    model = DigestItem
    extra = 0
    fields = ("section", "order", "item_image_preview")
    readonly_fields = ("item_image_preview",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("section").prefetch_related("articles")

    @admin.display(description="Image")
    def item_image_preview(self, obj):
        return _img_thumbnail(obj.best_image_url, w=80, h=50)


@admin.register(Digest)
class DigestAdmin(ModelAdmin):
    list_display = ("id", "date", "stage", "item_count", "created_at")
    list_display_links = ("id", "date")
    inlines = [DigestRunInline, DigestTranslationInline, DigestItemInlineShort]

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
    list_display = ("id", "item_topic", "section", "digest")
    list_display_links = ("id", "item_topic")
    list_filter = ("section", "digest__date")
    raw_id_fields = ("digest",)
    inlines = [DigestItemTranslationInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("section", "digest").prefetch_related("translations")

    @admin.display(description="Topic")
    def item_topic(self, obj):
        t = obj.translations.filter(language__is_default=True).first()
        return t.topic[:80] if t else f"Item #{obj.pk}"


# ── DigestRun ─────────────────────────────────────────────────


@admin.register(DigestRun)
class DigestRunAdmin(ModelAdmin):
    list_display = (
        "id", "digest", "model", "articles_collected", "stories_planned",
        "items_generated", "items_failed", "total_cost_usd",
        "plan_duration_ms", "write_duration_ms", "started_at",
    )
    list_display_links = ("id", "digest")
    readonly_fields = (
        "digest", "model", "items_per_section", "started_at", "completed_at",
        "articles_collected", "stories_planned",
        "plan_duration_ms", "plan_input_tokens", "plan_output_tokens", "plan_cost_usd",
        "items_generated", "items_failed",
        "write_duration_ms", "write_input_tokens", "write_output_tokens", "write_cost_usd",
        "total_cost_usd",
    )


# ── ItemPipeline ──────────────────────────────────────────────


@admin.register(ItemPipeline)
class ItemPipelineAdmin(ModelAdmin):
    list_display = (
        "id", "story_label", "cost_usd", "input_tokens", "output_tokens",
        "generation_ms", "generated_at",
    )
    list_display_links = ("id", "story_label")
    list_filter = ("item__digest__date",)
    readonly_fields = (
        "item", "story_label", "article_ids", "search_queries",
        "refined_articles", "analyzed_at", "refined_at", "generated_at", "translated_at",
        "input_tokens", "output_tokens", "cost_usd", "generation_ms",
        "articles_in_context", "context_tokens",
    )
