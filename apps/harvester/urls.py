from django.urls import path

from apps.harvester.views import harvester_dashboard, harvester_dashboard_api

urlpatterns = [
    path("dashboard/", harvester_dashboard, name="harvester_dashboard"),
    path("dashboard/api/", harvester_dashboard_api, name="harvester_dashboard_api"),
]
