from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Research, ResearchSource


class ResearchSourceInline(TabularInline):
    model = ResearchSource
    extra = 0
    raw_id_fields = ("article",)
    readonly_fields = ("relevance",)


@admin.register(Research)
class ResearchAdmin(ModelAdmin):
    list_display = ("id", "title_short", "item", "language", "chunks_used", "generation_time_ms", "created_at")
    list_display_links = ("id", "title_short")
    list_filter = ("language",)
    raw_id_fields = ("item",)
    inlines = [ResearchSourceInline]

    @admin.display(description="Title")
    def title_short(self, obj):
        return obj.title[:80] if obj.title else ""
