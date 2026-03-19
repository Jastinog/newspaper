from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/", include("apps.news.api_urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.news.urls")),
]
