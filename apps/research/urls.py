from django.urls import path

from . import views

urlpatterns = [
    path("research/<int:item_id>/", views.research, name="research"),
]
