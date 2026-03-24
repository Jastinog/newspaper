from django.urls import path

from . import views

urlpatterns = [
    path("article/<int:pk>/<slug:slug>/", views.article_detail, name="article_detail"),
    path("article/<int:pk>/", views.article_detail_redirect, name="article_detail_redirect"),
    path("search/", views.search, name="search"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
]
