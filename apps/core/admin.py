from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Language


@admin.register(Language)
class LanguageAdmin(ModelAdmin):
    list_display = ("id", "code", "name", "is_default", "is_active")
    list_display_links = ("id", "code")
    list_editable = ("is_active",)
    search_fields = ("code", "name")
