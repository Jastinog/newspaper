from django.urls import path

from . import views

urlpatterns = [
    path("articles/<int:article_id>/similar/", views.similar_articles_api, name="api_similar_articles"),
]
