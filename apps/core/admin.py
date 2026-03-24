from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Language


@admin.register(Language)
class LanguageAdmin(ModelAdmin):
    list_display = ("id", "code", "name")
    list_display_links = ("id", "code")
    search_fields = ("code", "name")
