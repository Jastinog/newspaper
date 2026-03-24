from django.contrib.sitemaps import views as sitemap_views
from django.urls import path

from . import views
from .sitemaps import sitemaps

urlpatterns = [
    path("", views.index, name="index"),
    path("digest/<str:date>/", views.index, name="digest_by_date"),
    path(
        "sitemap.xml",
        sitemap_views.index,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.index",
    ),
    path(
        "sitemap-<section>.xml",
        sitemap_views.sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
