from django.urls import path

from . import views

urlpatterns = [
    path("deep-dive/<int:item_id>/", views.deep_dive, name="deep_dive"),
]
