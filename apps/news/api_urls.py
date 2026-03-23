from django.urls import path

from . import views

urlpatterns = [
    path("articles/", views.ArticleListAPI.as_view(), name="api_articles"),
    path("articles/<int:pk>/", views.ArticleDetailAPI.as_view(), name="api_article_detail"),
    path("feeds/", views.FeedListAPI.as_view(), name="api_feeds"),
    path("feeds/<int:pk>/toggle/", views.toggle_feed_api, name="api_toggle_feed"),
    path("categories/", views.CategoryListAPI.as_view(), name="api_categories"),
    path("digest-items/<int:item_id>/similar/", views.similar_items_api, name="api_similar_items"),
]
