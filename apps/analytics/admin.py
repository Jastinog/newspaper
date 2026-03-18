from django.contrib import admin

from .models import PageView


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = ("path", "view_name", "device_type", "country", "is_bot", "timestamp")
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
