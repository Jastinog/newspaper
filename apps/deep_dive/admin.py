from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import DeepDive, DeepDiveSource


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
