from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.i18n import i18n_patterns

from apps.core.urls import seo_urlpatterns

urlpatterns = [
    path("admin/harvester/", include("apps.harvester.urls")),
    path("admin/analytics/", include("apps.analytics.dashboard_urls")),
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/", include("apps.feed.api_urls")),
    path("api/", include("apps.digest.api_urls")),
    path("analytics/", include("apps.analytics.urls")),
] + seo_urlpatterns

urlpatterns += i18n_patterns(
    path("", include("apps.core.urls")),
)

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Serve static via the finders so an ASGI server (daphne, `make ws`) can
    # serve them too — runserver's own static handler doesn't apply there.
    urlpatterns += staticfiles_urlpatterns()
