from django.urls import path

from apps.harvester.views import (
    harvester_dashboard,
    harvester_dashboard_api,
    harvester_stage_toggle,
    harvester_toggle,
)

urlpatterns = [
    path("dashboard/", harvester_dashboard, name="harvester_dashboard"),
    path("dashboard/api/", harvester_dashboard_api, name="harvester_dashboard_api"),
    path("dashboard/toggle/", harvester_toggle, name="harvester_toggle"),
    path("dashboard/stage-toggle/", harvester_stage_toggle, name="harvester_stage_toggle"),
]
