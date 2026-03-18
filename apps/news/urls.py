from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("article/<int:pk>/<slug:slug>/", views.article_detail, name="article_detail"),
    path("article/<int:pk>/", views.article_detail_redirect, name="article_detail_redirect"),
    path("deep-dive/<int:item_id>/", views.deep_dive, name="deep_dive"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
]
