from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.news.api_urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.news.urls")),
]
