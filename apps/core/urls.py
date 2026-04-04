from django.contrib.sitemaps import views as sitemap_views
from django.urls import path
from django.views.decorators.cache import cache_page

from . import views
from .sitemaps import sitemaps

cached_sitemap_index = cache_page(86400)(sitemap_views.index)
cached_sitemap_section = cache_page(86400)(sitemap_views.sitemap)

urlpatterns = [
    path("", views.index, name="index"),
    path("digest/<str:date>/", views.index, name="digest_by_date"),
    path("article/<int:pk>/<str:slug>/", views.article_detail, name="article_detail"),
    path("article/<int:pk>/", views.article_detail_redirect, name="article_detail_redirect"),
    path("search/", views.search, name="search"),
    path("feeds/", views.feeds_list, name="feeds_list"),
    path("feed/<int:pk>/", views.feed_detail, name="feed_detail"),
    path("articles/", views.articles_list, name="articles_list"),
    path("story/<int:item_id>/", views.story_detail, name="story_detail"),
    path("research/<int:item_id>/", views.research, name="research"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("pin/<slug:slug>/", views.toggle_pin, name="toggle_pin"),
]

# These should NOT be language-prefixed
seo_urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path(
        "sitemap.xml",
        cached_sitemap_index,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.index",
    ),
    path(
        "sitemap-<section>.xml",
        cached_sitemap_section,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
