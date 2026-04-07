from django.urls import path

from . import views

urlpatterns = [
    path("digest-items/<int:item_id>/sources/", views.item_sources_api, name="api_item_sources"),
    path("digest-items/<int:item_id>/similar/", views.similar_items_api, name="api_similar_items"),
]
