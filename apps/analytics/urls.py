from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("api/traffic-graph/", views.traffic_graph_api, name="traffic_graph_api"),
]
