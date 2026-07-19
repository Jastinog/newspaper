from django.contrib.sitemaps import views as sitemap_views
from django.urls import path
from django.views.decorators.cache import cache_page

from . import views
from .feeds import DigestFeed
from .news_sitemap import news_sitemap
from .sitemaps import sitemaps

cached_sitemap_index = cache_page(86400)(sitemap_views.index)
cached_sitemap_section = cache_page(86400)(sitemap_views.sitemap)

urlpatterns = [
    path("", views.home, name="index"),
    # Digest temporarily disabled — re-enable these routes to bring it back.
    # path("digest/", views.digest, name="digest"),
    # path("digest/<str:date>/", views.digest, name="digest_by_date"),
    # Must precede the <slug> route below — otherwise "summarize" matches as a slug.
    path("article/<int:pk>/summarize/", views.article_summarize, name="article_summarize"),
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
    path("lang/<str:lang>/", views.set_language_get, name="set_language_get"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("manifest.json", views.manifest_json, name="manifest_json"),
    path("feed/rss/", DigestFeed(), name="rss_feed"),
    path("sitemap-news.xml", news_sitemap, name="news_sitemap"),
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
