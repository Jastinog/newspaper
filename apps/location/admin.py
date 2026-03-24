from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Country, Region


@admin.register(Region)
class RegionAdmin(ModelAdmin):
    list_display = ("id", "name", "slug", "order", "country_count")
    list_display_links = ("id", "name")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Countries")
    def country_count(self, obj):
        return obj.countries.count()


@admin.register(Country)
class CountryAdmin(ModelAdmin):
    list_display = ("id", "code", "name", "region")
    list_display_links = ("id", "code", "name")
    list_filter = ("region",)
    search_fields = ("code", "name")
