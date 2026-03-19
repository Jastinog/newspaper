from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/today/", views.api_today, name="api_today"),
    path("api/views-over-time/", views.api_views_over_time, name="api_views_over_time"),
    path("api/top-pages/", views.api_top_pages, name="api_top_pages"),
    path("api/top-articles/", views.api_top_articles, name="api_top_articles"),
    path("api/top-referrers/", views.api_top_referrers, name="api_top_referrers"),
    path("api/geo/", views.api_geo, name="api_geo"),
    path("api/devices/", views.api_devices, name="api_devices"),
    path("api/categories/", views.api_categories, name="api_categories"),
]
