from django.contrib import admin
from django.utils.html import format_html, mark_safe
from unfold.admin import ModelAdmin

from .models import Activity, Client, Session
from .utils import country_flag, format_duration


def _format_source(source):
    """Render session source as a colored label."""
    if source == Session.Source.HTTP:
        return mark_safe('<span style="color:#e76f51;font-weight:600">HTTP</span>')
    return mark_safe('<span style="color:#2d6a4f;font-weight:600">WS</span>')


class ReadOnlyAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Client)
class ClientAdmin(ReadOnlyAdmin):
    list_display = (
        "client_id", "type_icon", "bot_name_display", "device_type",
        "browser", "os", "country_display", "city", "first_seen", "last_seen",
    )
    list_filter = ("is_bot", "device_type", "country", "city")
    search_fields = ("client_id", "browser", "os", "bot_name")
    readonly_fields = (
        "client_id", "first_seen", "last_seen", "device_type", "browser", "os",
        "user_agent", "ip_hash", "country", "country_name", "city", "is_bot", "bot_name",
    )

    @admin.display(description="Type", ordering="is_bot")
    def type_icon(self, obj):
        if obj.is_bot:
            return format_html(
                '<span title="Bot: {}" style="font-size:1.3em">🤖</span>',
                obj.bot_name or "Unknown bot",
            )
        return mark_safe('<span title="Human" style="font-size:1.3em">👤</span>')

    @admin.display(description="Bot Name", ordering="bot_name")
    def bot_name_display(self, obj):
        if obj.bot_name:
            return obj.bot_name
        if obj.is_bot:
            return mark_safe('<span style="opacity:0.5">Unknown bot</span>')
        return mark_safe("&mdash;")

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
        "session_id", "type_icon", "source_display", "client",
        "country_display", "city_display",
        "page_count", "active_time_display",
        "has_interaction", "verdict_display", "started_at", "ended_at",
    )
    list_filter = (
        "is_human", "has_interaction", "source",
        "client__country", "client__city",
    )
    search_fields = ("session_id", "client__country_name", "client__city")
    raw_id_fields = ("client",)
    list_select_related = ("client",)
    readonly_fields = (
        "session_id", "client", "source", "started_at", "ended_at", "page_count",
        "active_time", "has_interaction", "referrer", "referrer_domain", "is_human",
    )

    @admin.display(description="Type", ordering="is_human")
    def type_icon(self, obj):
        if obj.is_human:
            return mark_safe('<span title="Confirmed human" style="font-size:1.3em">👤</span>')
        if obj.client.is_bot:
            return format_html(
                '<span title="Bot: {}" style="font-size:1.3em">🤖</span>',
                obj.client.bot_name or "Unknown bot",
            )
        return mark_safe('<span title="Unconfirmed" style="font-size:1.3em;opacity:0.4">👤</span>')

    @admin.display(description="Source", ordering="source")
    def source_display(self, obj):
        return _format_source(obj.source)

    @admin.display(description="Verdict")
    def verdict_display(self, obj):
        if obj.is_human:
            return mark_safe('<span style="color:#2d6a4f;font-weight:600">✓ Human</span>')
        if obj.client.is_bot:
            name = obj.client.bot_name or "Bot"
            return format_html(
                '<span style="color:#c1121f;font-weight:600">🤖 {}</span>',
                name,
            )
        return mark_safe('<span style="opacity:0.5">?</span>')

    @admin.display(description="Country", ordering="client__country")
    def country_display(self, obj):
        flag = country_flag(obj.client.country)
        name = obj.client.country_name or obj.client.country or "\u2014"
        if flag:
            return format_html("{} {}", flag, name)
        return name

    @admin.display(description="City", ordering="client__city")
    def city_display(self, obj):
        return obj.client.city or "\u2014"

    @admin.display(description="Active Time")
    def active_time_display(self, obj):
        return format_duration(obj.active_time)


@admin.register(Activity)
class ActivityAdmin(ReadOnlyAdmin):
    list_display = ("type", "path", "view_name", "session_source", "timestamp")
    list_filter = ("type", "session__source")
    search_fields = ("path",)
    raw_id_fields = ("session", "article", "category")
    readonly_fields = (
        "session", "type", "path", "view_name", "article", "category",
        "timestamp", "meta",
    )

    @admin.display(description="Source", ordering="session__source")
    def session_source(self, obj):
        return _format_source(obj.session.source)
