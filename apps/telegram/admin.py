from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import SentItem, TelegramChannel, TelegramPost


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


@admin.register(TelegramPost)
class TelegramPostAdmin(ModelAdmin):
    list_display = ("channel", "digest", "status_display", "items_posted", "created_at")
    list_display_links = ("channel",)
    list_filter = ("status", "channel")
    date_hierarchy = "created_at"
    readonly_fields = ("channel", "digest", "status", "items_posted", "error_message", "created_at")

    @admin.display(description="Status")
    def status_display(self, obj):
        if obj.status == TelegramPost.Status.SUCCESS:
            return format_html('<span style="color:#2d6a4f;font-weight:600">OK</span>')
        return format_html(
            '<span style="color:#c1121f;font-weight:600" title="{}">ERR</span>',
            obj.error_message or "Unknown error",
        )

    def has_add_permission(self, request):
        return False


@admin.register(SentItem)
class SentItemAdmin(ModelAdmin):
    list_display = ("channel", "item", "sent_at")
    list_filter = ("channel",)
    readonly_fields = ("channel", "item", "sent_at")

    def has_add_permission(self, request):
        return False
