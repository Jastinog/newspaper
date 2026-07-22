from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    DigestSection, DigestSectionTranslation, SectionEmbedding,
)


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
