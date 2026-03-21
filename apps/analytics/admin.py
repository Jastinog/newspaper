from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Activity, Client, Session
from .utils import country_flag


class ReadOnlyAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Client)
class ClientAdmin(ReadOnlyAdmin):
    list_display = ("client_id", "device_type", "browser", "os", "country_display", "is_bot", "first_seen", "last_seen")
    list_filter = ("is_bot", "device_type", "country")
    search_fields = ("client_id", "browser", "os")
    readonly_fields = (
        "client_id", "first_seen", "last_seen", "device_type", "browser", "os",
        "user_agent", "ip_hash", "country", "country_name", "city", "is_bot",
    )

    @admin.display(description="Country", ordering="country")
    def country_display(self, obj):
        flag = country_flag(obj.country)
        name = obj.country_name or obj.country or "\u2014"
        if flag:
            return format_html("{} {}", flag, name)
        return name


@admin.register(Session)
class SessionAdmin(ReadOnlyAdmin):
    list_display = (
        "session_id", "client", "page_count", "active_time_display",
        "has_interaction", "is_human", "started_at", "ended_at",
    )
    list_filter = ("is_human", "has_interaction")
    search_fields = ("session_id",)
    raw_id_fields = ("client",)
    readonly_fields = (
        "session_id", "client", "started_at", "ended_at", "page_count",
        "active_time", "has_interaction", "referrer", "referrer_domain", "is_human",
    )

    @admin.display(description="Active Time")
    def active_time_display(self, obj):
        mins, secs = divmod(obj.active_time, 60)
        if mins:
            return f"{mins}m {secs}s"
        return f"{secs}s"


@admin.register(Activity)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ("type", "path", "view_name", "timestamp")
    list_filter = ("type",)
    search_fields = ("path",)
    raw_id_fields = ("session", "article", "category")
    readonly_fields = (
        "session", "type", "path", "view_name", "article", "category",
        "timestamp", "meta",
    )
