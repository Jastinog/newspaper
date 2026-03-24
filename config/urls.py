from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/", include("apps.feed.api_urls")),
    path("api/", include("apps.digest.api_urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("", include("apps.research.urls")),
    path("", include("apps.feed.urls")),
    path("", include("apps.digest.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
