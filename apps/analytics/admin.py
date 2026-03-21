from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import PageView


def _country_flag(code):
    """Convert 2-letter ISO country code to flag emoji."""
    if not code or len(code) != 2:
        return ""
    c = code.upper()
    return chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65)


@admin.register(PageView)
class PageViewAdmin(ModelAdmin):
    list_display = ("path", "view_name", "device_type", "country_display", "city", "is_bot", "timestamp")
    list_filter = ("is_bot", "device_type", "country", "view_name")
    search_fields = ("path", "referrer_domain")
    date_hierarchy = "timestamp"
    raw_id_fields = ("article", "category")
    readonly_fields = (
        "path",
        "view_name",
        "article",
        "category",
        "ip_hash",
        "session_hash",
        "user_agent",
        "is_bot",
        "device_type",
        "browser",
        "os",
        "referrer",
        "referrer_domain",
        "country",
        "country_name",
        "city",
        "timestamp",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Country", ordering="country")
    def country_display(self, obj):
        flag = _country_flag(obj.country)
        name = obj.country_name or obj.country or "—"
        if flag:
            return format_html("{} {}", flag, name)
        return name
