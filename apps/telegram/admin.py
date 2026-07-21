from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import TelegramChannel


@admin.register(TelegramChannel)
class TelegramChannelAdmin(ModelAdmin):
    list_display = ("name", "chat_id", "language", "is_active", "post_time", "top_n")
    list_display_links = ("name",)
    list_editable = ("is_active",)
    list_filter = ("is_active", "language")

    fieldsets = (
        (None, {
            "fields": ("name", "bot_token", "chat_id"),
        }),
        ("Posting", {
            "fields": ("language", "post_time", "top_n", "include_images", "is_active"),
        }),
    )
