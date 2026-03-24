from django.contrib.sitemaps import views as sitemap_views
from django.urls import path

from . import views
from .sitemaps import sitemaps

urlpatterns = [
    path("", views.index, name="index"),
    path("digest/<str:date>/", views.index, name="digest_by_date"),
    path("article/<int:pk>/<slug:slug>/", views.article_detail, name="article_detail"),
    path("article/<int:pk>/", views.article_detail_redirect, name="article_detail_redirect"),
    path("search/", views.search, name="search"),
    path("research/<int:item_id>/", views.research, name="research"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
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
