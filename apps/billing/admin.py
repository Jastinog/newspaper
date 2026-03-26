from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import APIUsage


@admin.register(APIUsage)
class APIUsageAdmin(ModelAdmin):
    list_display = ("id", "created_at", "service", "step", "api_type", "model", "total_tokens", "cost_usd")
    list_display_links = ("id",)
    list_filter = ("service", "step", "api_type", "model")
    date_hierarchy = "created_at"
    raw_id_fields = ("digest", "research", "item")
